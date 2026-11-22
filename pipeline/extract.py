"""Read the documents of queued contests with two independent readers and write the records.

Run: uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/extract.py [options]
  --limit N      read at most N candidates (default 10)
  --jobs N       candidates read at the same time (default 3)
  --key KEY      read these candidates only (repeatable), whatever their status
  --readers A,B  reader models (default READERS below); one reader gives method "single"
  --second N     also give up to N open single-reader records to the other reader

Scripts own all input and output: this script fetches the documents, a reader model only
reads the files it is given and writes out.json, and pipeline/validate.py decides whether
the result may be kept. Each reader works in its own folder under work/<key>/<model>/ and
never sees the other's work.

Outcome per candidate (data/candidates.json):
  both readings pass the checks and agree on the key facts  -> record, method "dual"
  both pass and disagree on a key fact                      -> record, method "disputed" (no page)
  (key facts: deadline and eligibility; when they disagree on attendance or fee, that fact is left out)
  one passes                                                -> record, method "single"
  both say skip                                             -> status "skipped"
  otherwise                                                 -> status "failed", tried again later
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
import upstream as up  # noqa: E402
from fetch import cached, fetch, load_index  # noqa: E402
from validate import ROOT, Cache, check, entry_deadline  # noqa: E402

WORK = ROOT / "work"
PIPELINE = ROOT / "pipeline"
CONTESTS = ROOT / "data/contests"
TODAY = cq.TODAY
READERS = ["gemini-4-hydrogen-medium", "gpt-6.1-sol"]
READER_TIMEOUT = 1500  # seconds per reader run
MAX_DOCS = 12
DOC_WORDS = re.compile(r"簡章|辦法|須知|規則|規章|要點|實施計畫|計畫書|附件|官網|官方網站|活動網站|競賽網站|比賽網站|活動網頁|詳見|點此")
DOC_EXT = re.compile(r"\.(pdf|docx?|odt|pptx?)(\?|$)", re.I)
NOT_DOCS = ("facebook.com", "instagram.com", "line.me", "lin.ee", "youtube.com", "youtu.be", "twitter.com", "x.com",
            "plurk.com", "threads.net", "apple.co", "google.com/maps", "docs.google.com/forms", "forms.gle")

fetch_lock = threading.Lock()
exhausted: set = set()  # reader models that hit their usage limit in this run
LIMIT_WORDS = ("usage limit", "rate limit", "quota", "RESOURCE_EXHAUSTED")
queue_lock = threading.Lock()


def log(key, msg):
    print(f"[{key}] {msg}", flush=True)


def get(url):
    """Text and links of a document, fetched once a day."""
    with fetch_lock:
        entry = load_index().get(url)
        if not entry or entry["fetched_at"][:10] != TODAY:
            try:
                fetch(url)
            except Exception as e:  # noqa: BLE001
                return None, f"{type(e).__name__}: {str(e)[:120]}"
        return cached(url), None


GENERIC = re.compile(r"\d+|第.{1,3}屆|全國|競賽|比賽|大賽|高中職|高級中等學校|學生|學校|國立|大學|科技|活動|辦理|舉辦|轉知|公告")


def bigrams(text: str) -> set:
    text = GENERIC.sub("", text)
    text = re.sub(r"[\s「」『』《》〈〉()（）\[\]【】、，,.:：！!？?_\-—–|｜/＆&]+", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def title_core(title: str) -> set:
    """Bigrams of the contest's own name: the part in 「」 when there is one."""
    m = re.search(r"「(.+)」", title)
    return bigrams(m.group(1) if m else title)


def attachment_score(link, title_grams) -> int:
    """How likely a link leads to this contest's rules. 2 or more is followed.

    Site menus on school pages link Drive files ("我是教師 Download") and policy PDFs; they
    score low because their text names no rule document and shares nothing with the title.
    """
    url, text = link["url"], link.get("text") or ""
    if not url.startswith("http") or any(bad in url for bad in NOT_DOCS):
        return 0
    score = 0
    shared = len(bigrams(text + " " + urllib.parse.unquote(url.rsplit("/", 1)[-1])) & title_grams)
    if title_grams and shared >= max(3, len(title_grams) // 2):
        score += 3
    if DOC_EXT.search(url):
        score += 1
    name = text + " " + urllib.parse.unquote(url.rsplit("/", 1)[-1])
    if DOC_EXT.search(url) and DOC_WORDS.search(name):  # an attached file named as rules or annex
        score += 2
    elif DOC_WORDS.search(text) and len(text) < 20:  # a news headline is longer
        score += 2
    if urlparse(url).netloc in ("drive.google.com", "docs.google.com"):
        score += 1
    return score


def gather(cand, extra=()):
    """Fetch the candidate's links, then the links in them most likely to be its rules. Returns ([doc], [problem])."""
    order = {"rules": 0, "registration": 1, "announcement": 2}
    urls = [u["url"] for u in sorted(cand["urls"], key=lambda u: order.get(u["role"], 3))]
    urls = [u for u in urls if not any(bad in u for bad in NOT_DOCS)] + list(extra)
    title_grams = title_core(cand["title"])
    docs, problems, seen = [], [], set()
    found = []
    for url in dict.fromkeys(urls):  # the candidate's own links first
        seen.add(url)
        got, err = get(url)
        if err:
            problems.append(f"{url}: {err}")
            continue
        text, links = got
        docs.append({"url": url, "text": text, "links": links, "kind": load_index()[url].get("kind", "")})
        found += [(attachment_score(l, title_grams), i, l["url"]) for i, l in enumerate(links)]
    # then attachments, one level deep, best first
    for score, _, url in sorted(found, key=lambda t: (-t[0], t[1])):
        if len(docs) >= MAX_DOCS or score < 2:
            break
        if url in seen:
            continue
        seen.add(url)
        got, err = get(url)
        if err:
            problems.append(f"{url}: {err}")
            continue
        text, links = got
        docs.append({"url": url, "text": text, "links": links, "kind": load_index()[url].get("kind", "")})
    return docs, problems


def prepare(folder: Path, cand, docs, asked: bool):
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "docs").mkdir(parents=True)
    lines = [f"# Task", "", f"Today: {TODAY}", f"Contest named in an announcement (a hint only): {cand['title']}"]
    if cand.get("deadline"):
        lines.append(f"Deadline given in that announcement (a hint only): {cand['deadline']}")
    if asked:
        lines.append("You have already asked for more documents once; write a record or a skip now.")
    lines += ["", "## Documents", ""]
    for i, d in enumerate(docs, 1):
        name = f"docs/{i:02d}.txt"
        body = d["text"] or "(this document gave no text: an image, a scanned PDF or an old .doc file)"
        (folder / name).write_text(f"URL: {d['url']}\nKIND: {d['kind']}\n---\n{body}\n", encoding="utf-8")
        links = "\n".join(f"- [{l.get('text') or ''}]({l['url']})" for l in d["links"][:150])
        (folder / f"docs/{i:02d}.links.txt").write_text(links + "\n", encoding="utf-8")
        lines.append(f"- `{name}`: {d['url']} ({d['kind']}, {len(d['text'])} characters, {len(d['links'])} links)")
    (folder / "task.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.copy(PIPELINE / "brief.md", folder / "brief.md")
    shutil.copy(ROOT / "data/schema/contest.schema.json", folder / "schema.json")
    shutil.copy(CONTESTS / "2026-thu-smart-sustainability.json", folder / "example.json")
    (folder / "check.py").write_text((PIPELINE / "check_out.py").read_text(encoding="utf-8").replace("__PIPELINE__", str(PIPELINE)),
                                     encoding="utf-8")


PROMPT = ("Read brief.md and task.md in the current folder and follow brief.md exactly. "
          "Write out.json in the current folder and run `python3 check.py` until it prints OK.")


def run_reader(model: str, folder: Path, prompt: str = PROMPT) -> str:
    """Run one reader in its folder. Returns a short status for the log."""
    log_path = folder / "reader.log"
    if model.startswith("gemini"):
        cmd = ["agy", "--model", model, "--dangerously-skip-permissions", "--print-timeout", "20m", "-p", prompt]
        stdin = subprocess.DEVNULL
        inp = None
    else:
        cmd = ["codex", "exec", "-m", model, "-c", 'model_reasoning_effort="medium"', "-s", "workspace-write",
               "-C", str(folder), "--skip-git-repo-check", "-o", str(folder / "last-message.md"), "-"]
        stdin, inp = None, prompt
    try:
        with open(log_path, "a", encoding="utf-8") as logf:
            subprocess.run(cmd, cwd=folder, stdin=stdin, input=inp, stdout=logf, stderr=subprocess.STDOUT,
                           text=True, timeout=READER_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return "timeout"
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    if not (folder / "out.json").exists() and any(w in tail for w in LIMIT_WORDS):
        exhausted.add(model)
        return "limit"
    return "ran"


def judge(folder: Path):
    """('record', rec, errors) | ('need', urls) | ('skip', reason) | ('none', message)."""
    out = folder / "out.json"
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return ("none", f"no valid out.json: {str(e)[:80]}")
    if isinstance(data, dict) and "need" in data:
        return ("need", [u for u in data["need"] if isinstance(u, str)][:6])
    if isinstance(data, dict) and "skip" in data:
        return ("skip", str(data["skip"]))
    tmp = folder / "final"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    rid = data.get("id") if isinstance(data, dict) else None
    if not isinstance(rid, str) or not re.match(r"^\d{4}-[a-z0-9-]+$", rid):
        return ("record", data, ["id is missing or not in the form YYYY-key"])
    path = tmp / f"{rid}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    errors, _, _ = check(path, Cache())
    return ("record", data, errors)


def read_once(model, cand, key):
    """One reader's work on one candidate, including one request for documents and one fix of errors."""
    folder = WORK / key / model
    if model in exhausted:
        return ("none", "usage limit reached")
    docs, problems = gather(cand)
    if not docs:
        return ("none", "no document could be fetched: " + "; ".join(problems)[:200])
    prepare(folder, cand, docs, asked=False)
    status = run_reader(model, folder)
    result = judge(folder)
    if result[0] == "need":
        offered = {l["url"] for d in docs for l in d["links"]}
        wanted = [u for u in result[1] if u in offered]
        log(key, f"{model} asks for {len(wanted)} more documents")
        docs, problems = gather(cand, extra=wanted)
        prepare(folder, cand, docs, asked=True)
        status = run_reader(model, folder)
        result = judge(folder)
    if result[0] == "record" and result[2]:
        (folder / "errors.md").write_text("\n".join(f"- {e}" for e in result[2]) + "\n", encoding="utf-8")
        status = run_reader(model, folder, PROMPT + " Your out.json failed the checks listed in errors.md: fix them.")
        result = judge(folder)
    if status in ("timeout", "limit") and result[0] == "none":
        return ("none", "the reader timed out" if status == "timeout" else "usage limit reached")
    return result


UNKNOWN = ("unknown", None, [])
NATIONWIDE = re.compile(r"全國|不限|國內外|境內外|全臺|全台")


def key_facts(rec) -> dict:
    """The facts a page needs: the deadline and who may enter. Two readings that contradict on one of
    these give method "disputed" and no page."""
    e = rec["eligibility"]
    regions = sorted(e["regions"])
    if regions and all(NATIONWIDE.search(r) for r in regions):
        regions = ["全國"]
    return {
        # the deadline the pages show: the last day a new entrant can join
        "截止日": (entry_deadline(rec) or (None,))[0],
        # whether senior-high and vocational students may enter; readers differ on listing 五專 or
        # 國中 beside them, which the catalogue does not turn on
        "參賽對象": sorted(set(e["levels"]) & {"高中", "高職"}),
        "分組": e["division"],
        "地區": regions,
        "推薦": e["nomination"],
    }


# Other facts that are compared: a contradiction removes the fact from the record (the page leaves it
# out) instead of withholding the page; a gap is not reported.
SIDE_FACTS = {"到場": "attendance", "費用": "fee"}


def differences(fa, fb):
    contradictions, gaps = [], []
    for k in fa:
        if fa[k] == fb[k]:
            continue
        if fa[k] in UNKNOWN or fb[k] in UNKNOWN:
            gaps.append(k)
        else:
            contradictions.append(f"{k}：{fa[k]} 對 {fb[k]}")
    return contradictions, gaps


def compare(a, b):
    """Compare two readings and settle the record `a`. Returns (method, note). Side facts on which the
    readings contradict are set to unknown in `a`."""
    contradictions, gaps = differences(key_facts(a), key_facts(b))
    side, _ = differences({k: a[f]["value"] for k, f in SIDE_FACTS.items()}, {k: b[f]["value"] for k, f in SIDE_FACTS.items()})
    notes = []
    for item in side:
        a[SIDE_FACTS[item.split("：")[0]]].update(value="unknown", basis="unread", evidence=[])
    if side:
        notes.append("兩次讀取不一致，未列出：" + "；".join(side))
    if contradictions:
        return "disputed", "；".join(["兩次讀取的關鍵事實不一致：" + "；".join(contradictions), *notes])
    if gaps:
        return "single", "；".join(["第二次讀取沒有確認：" + "、".join(gaps), *notes])
    return "dual", "；".join(notes) or None


def place(rec, cand, readers, method, note):
    """Fill the fields the script owns and write the record. Returns its id."""
    cand_urls = {cq.same_url(u["url"]) for u in cand["urls"]}
    if cand.get("record"):  # read again for an existing record: keep its id
        rec["id"] = cand["record"]
    else:  # a record that shares a link with the candidate is the same contest
        for other in sorted(CONTESTS.glob("*.json")):
            old = json.loads(other.read_text(encoding="utf-8"))
            if {cq.same_url(u) for u in cq.record_urls(old)} & cand_urls:
                rec["id"] = old["id"]
                break
    rid = rec["id"]
    path = CONTESTS / f"{rid}.json"
    first_seen = cand.get("first_seen") or TODAY
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if {cq.same_url(u) for u in cq.record_urls(old)} & cand_urls or old["title"] == rec["title"]:
            first_seen = min(old["first_seen"], first_seen)
        else:
            n = 2
            while (CONTESTS / f"{rid}-{n}.json").exists():
                n += 1
            rid = f"{rid}-{n}"
            rec["id"] = rid
            path = CONTESTS / f"{rid}.json"
    rec["schema"] = 1
    found = []
    for u in cand["urls"]:
        if u["role"] == "announcement" or not found:
            found.append({"name": u["name"] or urlparse(u["url"]).netloc, "url": u["url"]})
    rec["found_via"] = found
    rec["first_seen"] = first_seen
    rec["updated"] = TODAY
    v = rec["verification"]
    v.update(last_verified=TODAY, method=method, readers=readers, note=note)
    errors, _, level = check_written(rec)
    if errors:
        raise ValueError("record fails after the script's fields were filled: " + errors[0])
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # What the readers read is what pnpm upstream and the daily re-check compare with.
    up.save_baselines({rid: up.baseline_from_cache(rec)})
    return rid, level


def check_written(rec):
    tmp = WORK / "_final"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{rec['id']}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return check(path, Cache())


def process(cand, readers):
    key = cand["key"]
    log(key, f"start: {cand['title'][:40]}")
    with ThreadPoolExecutor(max_workers=len(readers)) as pool:
        results = list(pool.map(lambda m: read_once(m, cand, key), readers))
    good = [(m, r[1]) for m, r in zip(readers, results) if r[0] == "record" and not r[2]]
    skips = [r[1] for r in results if r[0] == "skip"]
    summary = "; ".join(f"{m}: {r[0]}" + (f" ({len(r[2])} errors)" if r[0] == "record" and r[2] else "")
                        + (f" ({r[1][:60]})" if r[0] in ("skip", "none") else "") for m, r in zip(readers, results))
    outcome = {"status": "failed", "record": None, "note": summary}
    if len(good) == 2:
        method, note = compare(good[0][1], good[1][1])
        rid, level = place(good[0][1], cand, [m for m, _ in good], method, note)
        outcome = {"status": "done", "record": rid, "note": f"{method}, {level}"}
    elif len(good) == 1:
        others = [m for m in readers if m != good[0][0]]
        rid, level = place(good[0][1], cand, [good[0][0]], "single", None)
        outcome = {"status": "done", "record": rid,
                   "note": f"single ({', '.join(others)} did not pass: {summary})" if others else "single"}
    elif skips and len(skips) == len(readers):
        outcome = {"status": "skipped", "record": None, "note": skips[0]}
    with queue_lock:
        queue = cq.load()
        for c in queue:
            if c["key"] == key:
                # a failed re-read keeps the id of the record it reads again
                c.update({k: v for k, v in outcome.items() if v is not None or k != "record"})
                c["attempts"] = c.get("attempts", 0) + 1
                if c["status"] == "failed" and c["attempts"] >= cq.MAX_ATTEMPTS:
                    c["status"] = "given_up"
        cq.save(queue)
    log(key, f"{outcome['status']}: {outcome['record'] or ''} {outcome['note'] or ''}"[:300])
    return outcome


def second_reading(path: Path, readers) -> str:
    """Give a record read by one reader to a reader that has not read it, and compare."""
    rec = json.loads(path.read_text(encoding="utf-8"))
    v = rec["verification"]
    missing = [m for m in readers if m not in (v.get("readers") or []) and m not in exhausted]
    if not missing:
        return "no reader left"
    model = missing[0]
    queue = cq.load()
    cand = next((c for c in queue if c.get("record") == rec["id"]), None)
    if not cand:
        cand = {"key": f"r-{rec['id']}", "title": rec["title"], "deadline": None, "first_seen": rec["first_seen"],
                "urls": [{"url": u, "role": "rules", "name": ""} for u in sorted(cq.record_urls(rec))]}
    result = read_once(model, cand, cand["key"])
    if result[0] != "record" or result[2]:
        return f"{model}: {result[0]}" + (f" ({len(result[2])} errors)" if result[0] == "record" else f" ({str(result[1])[:80]})")
    method, note = compare(rec, result[1])
    v.update(method=method, note=note, readers=[*(v.get("readers") or []), model])
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"{model}: {method}"


def second_readings(readers, limit, jobs):
    """Give up to `limit` open single-reader records to the other reader, soonest deadline first:
    the second reader's quota is the scarce one, and a wrong deadline hurts most when it is near."""
    todo = []
    for path in sorted(CONTESTS.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        v = rec["verification"]
        due = entry_deadline(rec)
        if v["method"] == "single" and len(v.get("readers") or []) < len(readers) and (due is None or due[0] >= TODAY):
            todo.append(((due or ("9999",))[0], path))
    todo = [path for _, path in sorted(todo)[:limit]]
    print(f"second readings: {len(todo)}", flush=True)

    def one(path):
        try:
            outcome = second_reading(path, readers)
        except Exception as e:  # noqa: BLE001
            outcome = f"{type(e).__name__}: {str(e)[:120]}"
        log(path.stem, "second reading: " + outcome)
        return path.stem, outcome

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, todo))


def safe_process(cand, readers):
    try:
        return process(cand, readers)
    except Exception as e:  # noqa: BLE001  one candidate must not stop the others
        note = f"{type(e).__name__}: {str(e)[:200]}"
        with queue_lock:
            queue = cq.load()
            for c in queue:
                if c["key"] == cand["key"]:
                    c.update(status="failed", note=note, attempts=c.get("attempts", 0) + 1)
            cq.save(queue)
        log(cand["key"], "failed: " + note)
        return {"status": "failed", "record": None, "note": note}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--key", action="append", default=[])
    ap.add_argument("--readers", default=",".join(READERS))
    ap.add_argument("--second", type=int, default=0, help="also give up to N single-reader records to the other reader")
    args = ap.parse_args()
    readers = [r for r in args.readers.split(",") if r]
    if args.second and not args.key and args.limit == 0:
        second_readings(READERS, args.second, args.jobs)
        return
    queue = cq.load()
    if args.key:
        todo = [c for c in queue if c["key"] in args.key]
    else:
        todo = [c for c in queue if c["status"] == "new" or (c["status"] == "failed" and c.get("attempts", 0) < cq.MAX_ATTEMPTS)]
        todo.sort(key=lambda c: (c["status"] != "new", c.get("deadline") or "9999"))
        todo = todo[: args.limit]
    print(f"reading {len(todo)} candidates with {', '.join(readers)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        outcomes = list(pool.map(lambda c: safe_process(c, readers), todo))
    counts = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    print("done:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if args.second:
        second_readings(READERS, args.second, args.jobs)


if __name__ == "__main__":
    main()
