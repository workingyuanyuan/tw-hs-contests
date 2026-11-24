"""Reading tasks: the documents of one queued contest, read by an agent in a fresh context.

pipeline/daily.py calls this module; it has no command of its own.

Scripts own all input and output. `write_task` fetches the candidate's documents and writes a task
folder (work/tasks/<key>-<reading>/) with their texts, pipeline/brief.md, the schema, an example
record and check.py. The agent that runs the task reads only that folder and writes out.json (and
its model's name in model.txt); it never fetches and never sees another reading of the contest.
`finish_first` and `finish_second` judge out.json with pipeline/validate.py and settle the result.

A contest is read twice, each time in a fresh context, at the first and at a later round:
  first reading passes the checks                    -> record, method "single" (level checked)
  second reading passes and agrees on the key facts  -> method "dual" (verified)
  second reading passes and disagrees on a key fact  -> method "disputed" (no page)
  (key facts: deadline and eligibility; when they disagree on attendance or fee, that fact is left out)
  first reading says skip                            -> status "skipped"
  first reading asks for documents ({"need": [...]}) -> read again with them, once
  otherwise                                          -> status "failed", tried again later
"""
import json
import re
import shutil
import sys
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
import upstream as up  # noqa: E402
from fetch import cached, fetch, load_index  # noqa: E402
from validate import ROOT, Cache, check, entry_deadline, passed  # noqa: E402

TASKS = ROOT / "work/tasks"
PIPELINE = ROOT / "pipeline"
CONTESTS = ROOT / "data/contests"
TODAY = cq.TODAY
MAX_DOCS = 12
DOC_WORDS = re.compile(r"簡章|辦法|須知|規則|規章|要點|實施計畫|計畫書|附件|官網|官方網站|活動網站|競賽網站|比賽網站|活動網頁|詳見|點此")
DOC_EXT = re.compile(r"\.(pdf|docx?|odt|pptx?)(\?|$)", re.I)
NOT_DOCS = ("facebook.com", "instagram.com", "line.me", "lin.ee", "youtube.com", "youtu.be", "twitter.com", "x.com",
            "plurk.com", "threads.net", "apple.co", "google.com/maps", "docs.google.com/forms", "forms.gle")


def get(url):
    """Text and links of a document, fetched once a day."""
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


def write_task(folder: Path, cand, reading: int, record=None):
    """Fetch the candidate's documents and write its task folder. Returns None, or why no folder was written."""
    need = (cand.get("second") or {}).get("need") if reading == 2 else cand.get("need")
    docs, problems = gather(cand, extra=need or ())
    if not docs:
        return "no document could be fetched: " + "; ".join(problems)[:200]
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "docs").mkdir(parents=True)
    lines = ["# Task", "", f"Today: {TODAY}", f"Contest named in an announcement (a hint only): {cand['title']}"]
    if cand.get("deadline"):
        lines.append(f"Deadline given in that announcement (a hint only): {cand['deadline']}")
    if need:
        lines.append("A reader has already asked for more documents once; write a record or a skip now.")
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
    shutil.copy(PIPELINE / "check_out.py", folder / "check.py")
    offered = sorted({l["url"] for d in docs for l in d["links"][:150]})
    task = {"kind": "read", "key": cand["key"], "reading": reading, "record": record, "asked": bool(need),
            "docs": [d["url"] for d in docs], "offered": offered}
    (folder / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return None


def reading_shape(data, task):
    """(kind, problems) of a reading's out.json before the publishing checks: kind is "need", "skip"
    or "record". Shared with check.py, so that what the reader is told OK is what finish accepts."""
    if not isinstance(data, dict):
        return "record", ["out.json must be one JSON object"]
    if "need" in data:
        urls = data["need"]
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
            return "need", ['"need" must be a list of 1 to 6 links']
        if task.get("asked"):
            return "need", ["more documents were asked for once already: write a record or a skip"]
        if len(urls) > 6 or not set(urls) <= set(task.get("offered", [])):
            return "need", ['"need" takes at most 6 links, copied exactly from a docs/NN.links.txt file']
        return "need", []
    if "skip" in data:
        if not isinstance(data["skip"], str) or not data["skip"].strip():
            return "skip", ['"skip" must give the reason']
        return "skip", []
    rid = data.get("id")
    if not isinstance(rid, str) or not re.fullmatch(r"\d{4}-[a-z0-9-]+", rid):
        return "record", ["id is missing or not in the form YYYY-key"]
    supplied = set(task.get("docs", []))
    foreign = sorted({ev.get("url") for f in evidence_lists(data) for ev in f if isinstance(ev, dict)} - supplied - {None})
    if supplied and foreign:
        return "record", [f"evidence cites a document that is not in docs/: {foreign[0]}"]
    return "record", []


def evidence_lists(rec):
    """Every evidence list in a record, whatever its shape, for the check above (schema errors come later)."""
    found = []
    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("evidence"), list):
                found.append(x["evidence"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(rec)
    return found


def reader_of(folder: Path) -> str:
    """The model the agent named in model.txt, else "unknown"."""
    try:
        name = (folder / "model.txt").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return "unknown"
    return re.sub(r"[^\w.:/@+-]", "", name)[:60] or "unknown"


def judge(folder: Path):
    """('record', rec, errors) | ('need', urls) | ('skip', reason) | ('none', message) | ('missing', None)."""
    out = folder / "out.json"
    if not out.exists():
        return ("missing", None)
    task = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return ("none", f"no valid out.json: {str(e)[:80]}")
    kind, problems = reading_shape(data, task)
    if problems and kind != "record":
        return ("none", problems[0])
    if kind == "need":
        return ("need", data["need"])
    if kind == "skip":
        return ("skip", data["skip"].strip())
    if problems:
        return ("record", data, problems)
    tmp = folder / "final"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    path = tmp / f"{data['id']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    errors, _, _ = check(path, Cache(strict=True))
    return ("record", data, errors)


def describe(result) -> str:
    kind = result[0]
    if kind == "record":
        return f"record ({len(result[2])} errors: {result[2][0][:80]})" if result[2] else "record"
    return f"{kind} ({str(result[1])[:80]})" if result[1] else kind


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


def same_edition(a, b) -> bool:
    """Organizers reuse a page for the next edition; a shared link alone does not make two readings one record."""
    return re.sub(r"\s+", "", a["edition"]) == re.sub(r"\s+", "", b["edition"])


def place(rec, cand, readers, method, note):
    """Fill the fields the script owns and write the record. Returns its id."""
    cand_urls = {cq.same_url(u["url"]) for u in cand["urls"]}
    if cand.get("record"):  # read again for an existing record: keep its id
        rec["id"] = cand["record"]
    else:  # a record of the same edition that shares a link with the candidate is the same contest
        for other in sorted(CONTESTS.glob("*.json")):
            old = json.loads(other.read_text(encoding="utf-8"))
            if same_edition(old, rec) and {cq.same_url(u) for u in cq.record_urls(old)} & cand_urls:
                rec["id"] = old["id"]
                break
    rid = rec["id"]
    path = CONTESTS / f"{rid}.json"
    first_seen = cand.get("first_seen") or TODAY
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if cand.get("record") or same_edition(old, rec) and (
                {cq.same_url(u) for u in cq.record_urls(old)} & cand_urls or old["title"] == rec["title"]):
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
    tmp = ROOT / "work/_final"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{rec['id']}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return check(path, Cache(strict=True))


def finish_first(cand, folder: Path) -> str:
    """Settle a first reading in the candidate (changed in place). Returns a line for the log."""
    result = judge(folder)
    if result[0] == "missing":
        return "not run"
    if result[0] == "need":
        cand["need"] = result[1]
        return f"asks for {len(cand['need'])} more documents"
    cand.pop("need", None)
    cand["attempts"] = cand.get("attempts", 0) + 1
    if result[0] == "record" and not result[2]:
        rid, level = place(result[1], cand, [reader_of(folder)], "single", None)
        cand.update(status="done", record=rid, note=f"single, {level}")
        cand.pop("second", None)  # a new reading of the record: its second reading starts over
        return f"done: {rid} ({level})"
    if result[0] == "skip":
        cand.update(status="skipped", note=result[1][:200])
        return "skipped: " + result[1][:80]
    cand.update(status="failed", note=describe(result))
    if cand["attempts"] >= cq.MAX_ATTEMPTS:
        cand["status"] = "given_up"
    return f"{cand['status']}: {cand['note']}"


def finish_second(cand, folder: Path) -> str:
    """Compare a second reading with the record it reads again. Returns a line for the log."""
    result = judge(folder)
    task = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    second = cand.setdefault("second", {"attempts": 0})
    if result[0] == "missing":
        return "not run"
    if result[0] == "need":
        second["need"] = result[1]
        return f"asks for {len(second['need'])} more documents"
    second.pop("need", None)
    second["attempts"] += 1
    path = CONTESTS / f"{task['record']}.json"
    if not path.exists():
        second["note"] = "the record is gone"
        return second["note"]
    if result[0] != "record" or result[2]:
        second["note"] = describe(result)
        return f"no second reading: {second['note']}"
    rec = json.loads(path.read_text(encoding="utf-8"))
    v = rec["verification"]
    method, note = compare(rec, result[1])
    v.update(method=method, note=note, readers=[*(v.get("readers") or []), reader_of(folder)])
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    second["note"] = method
    return f"second reading: {method}"


def first_todo(queue, limit: int) -> list:
    """Candidates to read, at most `limit`: re-reads of records first, then by deadline."""
    todo = [c for c in queue if c["status"] == "new" or (c["status"] == "failed" and c.get("attempts", 0) < cq.MAX_ATTEMPTS)]
    todo.sort(key=lambda c: (c.get("record") is None, c["status"] != "new", c.get("deadline") or "9999",
                             c.get("first_seen") or ""))
    return todo[:limit]


def second_todo(queue, limit: int) -> list:
    """(candidate, record id) of open records read once, soonest deadline first, at most `limit`.
    A record with no candidate (read before the queue existed) gets one."""
    by_record = {c["record"]: c for c in queue if c.get("record")}
    todo = []
    for path in sorted(CONTESTS.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        due = entry_deadline(rec)
        v = rec["verification"]
        if v["method"] != "single" or len(v.get("readers") or []) >= 2 or (due and passed(due)):
            continue  # a second reading that left a key fact unconfirmed keeps the record single
        cand = by_record.get(rec["id"])
        if cand and (cand["status"] in ("new", "failed") or (cand.get("second") or {}).get("attempts", 0) >= cq.MAX_ATTEMPTS):
            continue  # being read again, or its second readings failed
        todo.append((due or ("9999-12-31", ""), rec))
    out = []
    for _, rec in sorted(todo, key=lambda t: (t[0][0], t[0][1] or "24:00"))[:limit]:
        cand = by_record.get(rec["id"])
        if not cand:
            cand = {"key": cq.next_key(queue), "title": rec["title"], "deadline": None,
                    "urls": [{"url": u, "role": "rules", "name": ""} for u in sorted(cq.record_urls(rec))],
                    "seen_in": "record", "first_seen": rec["first_seen"], "last_seen": TODAY,
                    "status": "done", "attempts": 0, "record": rec["id"], "note": None}
            queue.append(cand)
            by_record[rec["id"]] = cand
        out.append((cand, rec["id"]))
    return out
