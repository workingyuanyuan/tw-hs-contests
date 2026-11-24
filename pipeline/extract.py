"""Reading tasks: the documents of one queued contest, read by an agent in a fresh context.

pipeline/daily.py calls this module; it has no command of its own.

Scripts own all input and output. `write_task` fetches the candidate's documents, and the links in
them most likely to be its rules, two hops deep (an announcement, the organizer's page it links,
the rules that page attaches), and writes a task folder (work/tasks/<key>-<reading>/) with their
texts (an image or a scanned PDF as its OCR text, with the original file beside it),
pipeline/brief.md, the schema, an example record and check.py. The agent that runs the task reads only that folder and writes out.json (and
its model's name in model.txt); it never fetches and never sees another reading of the contest.
`finish_first` and `finish_second` judge out.json with pipeline/validate.py and settle the result.

A contest is read twice, each time in a fresh context, at the first and at a later round:
  first reading passes the checks                    -> record, method "single" (level checked)
  second reading passes and agrees on the key facts  -> method "dual" (verified)
  second reading passes and disagrees on a key fact  -> method "disputed" (no page)
  (key facts: deadline and eligibility; when they disagree on attendance, fee or the AI rules, that
  fact is left out)
  first reading says skip                            -> status "skipped"
  first reading asks for documents ({"need": [...]}) -> read again with them, once
  otherwise                                          -> status "failed", tried again later
A candidate whose documents could not be fetched, whose readings failed MAX_ATTEMPTS times, or
whose record lacks a checked deadline or eligibility is searched for once (pipeline/search.py:
an agent looks for the organizer's page or rules, a script keeps what names the contest and
edition) and read again with what was found. A candidate given up is read once more after
RETRY_DAYS, while it may still be open.
"""
import json
import re
import shutil
import sys
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
import upstream as up  # noqa: E402
from fetch import CACHE, cached, fetch, load_index, mark_gone  # noqa: E402
from validate import ROOT, Cache, check, entry_deadline, passed  # noqa: E402

TASKS = ROOT / "work/tasks"
PIPELINE = ROOT / "pipeline"
CONTESTS = ROOT / "data/contests"
TODAY = cq.TODAY
MAX_DOCS = 12
HOPS = 2  # links followed from the candidate's own documents, then from the documents they led to
LAST_HOP = 3  # documents kept for the last hop: an announcement with many annexes leaves room for the rules its organizer's page links
RETRY_DAYS = 7
DOC_WORDS = re.compile(r"簡章|辦法|須知|規則|規章|要點|實施計畫|計畫書|附件|切結書|聲明書|同意書|常見問答|常見問題|"
                       r"官網|官方網站|活動網站|競賽網站|比賽網站|活動網頁|詳見|點此|(?i:FAQ|Q&A)")
DOC_EXT = re.compile(r"\.(pdf|docx?|odt|pptx?)(\?|$)", re.I)
NOT_DOCS = ("facebook.com", "instagram.com", "line.me", "lin.ee", "youtube.com", "youtu.be", "twitter.com", "x.com",
            "plurk.com", "threads.net", "apple.co", "google.com/maps", "docs.google.com/forms", "forms.gle")


def get(url):
    """Text and links of a document, fetched once a day."""
    entry = load_index().get(url)
    if not entry or entry.get("gone") or entry.get("fetched_at", "")[:10] != TODAY:
        try:
            fetch(url)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            mark_gone(url, err)
            return None, err
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
    """Fetch the candidate's links, then the links in them most likely to be its rules, HOPS deep,
    best first at each hop. Returns ([doc], [problem])."""
    order = {"rules": 0, "registration": 1, "announcement": 2}
    urls = [u["url"] for u in sorted(cand["urls"], key=lambda u: order.get(u["role"], 3))]
    urls = [u for u in urls if not any(bad in u for bad in NOT_DOCS)] + list(extra)
    title_grams = title_core(cand["title"])
    docs, problems, seen = [], [], set()

    def add(url):
        seen.add(url)
        got, err = get(url)
        if err:
            problems.append(f"{url}: {err}")
            return []
        text, links = got
        entry = load_index()[url]
        docs.append({"url": url, "text": text, "links": links, "kind": entry.get("kind", ""), "file": entry.get("file"),
                     "pages_unread": entry.get("pages_unread")})
        return [(attachment_score(l, title_grams), len(docs), i, l["url"]) for i, l in enumerate(links)]

    found = []
    for url in dict.fromkeys(urls):  # the candidate's own links first
        found += add(url)
    for hop in range(HOPS):
        later = []
        room = MAX_DOCS if hop + 1 == HOPS else MAX_DOCS - LAST_HOP
        for score, _, _, url in sorted(found, key=lambda t: (-t[0], t[1], t[2])):
            if len(docs) >= room or score < 2:
                break
            if url not in seen:
                later += add(url)
        found = later if hop + 1 < HOPS else []
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
        line = f"- `{name}`: {d['url']} ({d['kind']}, {len(d['text'])} characters, {len(d['links'])} links)"
        if d.get("pages_unread"):
            line += f"; {d['pages_unread']} scanned pages were not read, so this document is incomplete"
        if d.get("file") and (CACHE / d["file"]).exists():
            original = f"docs/{i:02d}{Path(d['file']).suffix}"
            shutil.copy(CACHE / d["file"], folder / original)
            line += f"; text read by OCR from `{original}`"
        lines.append(line)
    (folder / "task.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.copy(PIPELINE / "brief.md", folder / "brief.md")
    shutil.copy(ROOT / "data/schema/contest.schema.json", folder / "schema.json")
    shutil.copy(PIPELINE / "example.json", folder / "example.json")  # a fixed copy: a live record can be set aside
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
    cited = [ev.get("url") if isinstance(ev, dict) else ev for f in evidence_lists(data) for ev in f]
    if not all(isinstance(u, str) for u in cited):
        return "record", ["every evidence item must be an object whose url is a string"]
    foreign = sorted(set(cited) - supplied)
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
SIDE_FACTS = {"到場": "attendance", "費用": "fee", "AI 規定": "ai_policy"}


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


CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(s: str):
    """An ordinal written in digits or in Chinese numerals (十七, 二十四, 一百零二); None for anything else."""
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in CN_DIGITS:
            num = CN_DIGITS[ch]
        elif ch in "十百":
            total += (num or 1) * (10 if ch == "十" else 100)
            num = 0
        else:
            return None
    return total + num


def ordinal(edition: str):
    """The N of 「第 N 屆」 in an edition, or None."""
    m = re.search(r"第\s*([0-9０-９]+|[〇零一二兩三四五六七八九十百]+)\s*[屆届]", edition)
    return cn_number(m.group(1)) if m else None


def same_edition(a, b) -> bool:
    """Organizers reuse a page for the next edition; a shared link alone does not make two readings one record.
    Readers write one edition in several ways (「第 4 屆」 and 「第 4 屆（115 年度）」, 「2027 第五屆」 and
    「第五屆」): where both name an ordinal, the ordinal decides, unless both name years and no year is shared."""
    ea, eb = (re.sub(r"\s+", "", x.get("edition") or "") for x in (a, b))
    oa, ob = ordinal(ea), ordinal(eb)
    if oa is not None and ob is not None:
        ya, yb = (set(re.findall(r"20\d\d", e)) for e in (ea, eb))
        return oa == ob and not (ya and yb and not ya & yb)
    return ea == eb


def same_contest_by_title(a, b) -> bool:
    """The same title (spaces aside) and a shared organizer: two readings of one contest whose
    announcements shared no link."""
    title = lambda r: re.sub(r"\s+", "", r.get("title") or "")
    orgs = lambda r: {re.sub(r"\s+", "", o.get("name") or "") for o in r.get("organizers") or []} - {"", "unknown"}
    return bool(title(a)) and title(a) == title(b) and bool(orgs(a) & orgs(b))


def place(rec, cand, readers, method, note):
    """Fill the fields the script owns and write the record. Returns its id."""
    cand_urls = {cq.same_url(u["url"]) for u in cand["urls"]}
    old_path = CONTESTS / f"{cand.get('record')}.json"
    if not old_path.exists():  # set aside while it waited to be read again
        old_path = ROOT / "data/stale" / f"{cand.get('record')}.json"
    if cand.get("record") and old_path.exists() and not same_edition(json.loads(old_path.read_text(encoding="utf-8")), rec):
        cand["record"] = None  # its page now describes another edition, which is a record of its own
    if cand.get("record"):  # read again for an existing record: keep its id
        rec["id"] = cand["record"]
    else:  # a record of the same edition that shares a link with the candidate, or else has its title, is the same contest
        olds = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTESTS.glob("*.json"))]
        olds = [o for o in olds if same_edition(o, rec)]
        match = next((o for o in olds if {cq.same_url(u) for u in cq.record_urls(o)} & cand_urls), None) \
            or next((o for o in olds if same_contest_by_title(o, rec)), None)
        if match:
            rec["id"] = match["id"]
    rid = rec["id"]
    path = CONTESTS / f"{rid}.json"
    first_seen = cand.get("first_seen") or TODAY
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if cand.get("record") or same_edition(old, rec) and (
                {cq.same_url(u) for u in cq.record_urls(old)} & cand_urls
                or re.sub(r"\s+", "", old["title"]) == re.sub(r"\s+", "", rec["title"])):
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
    (ROOT / "data/stale" / f"{rid}.json").unlink(missing_ok=True)  # set aside earlier, read again now
    # What the readers read is what pnpm upstream and the daily re-check compare with.
    up.save_baselines({rid: up.baseline_from_cache(rec)})
    return rid, level


METHOD_RANK = {"dual": 0, "single": 1}


def merge_duplicates(queue) -> list:
    """Make one record of the records that describe one contest (the same edition, the same title and
    a shared organizer) written under two ids before place() matched them: the readers wrote the
    edition differently, or the announcements shared no link. The id seen first stays, so an address
    already published stays. Its content is the best-verified reading, the newest of equals, with its
    baselines; the other ids are removed and their candidates name the id kept. The queue is saved
    before any record changes, so a run stopped halfway finds the same group again. Returns lines for
    the log."""
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTESTS.glob("*.json"))]
    recs.sort(key=lambda r: (r.get("first_seen") or "", bool(re.search(r"-\d+$", r["id"])), r.get("updated") or "", r["id"]))
    groups = []
    for r in recs:
        group = next((g for g in groups if same_edition(g[0], r) and same_contest_by_title(g[0], r)), None)
        group.append(r) if group else groups.append([r])
    groups = [g for g in groups if len(g) > 1]
    if not groups:
        return []
    gone = {r["id"]: g[0]["id"] for g in groups for r in g[1:]}
    for c in queue:
        if c.get("record") in gone:
            c["record"] = gone[c["record"]]
    cq.save(queue)
    baselines = (up.load_manifest() or {}).get("records") or {}
    lines, entries = [], {}
    for g in groups:
        cid = g[0]["id"]
        best = min(g, key=lambda r: (METHOD_RANK.get(r["verification"].get("method"), 2),
                                     -int((r.get("updated") or "0").replace("-", "") or 0), r["id"] != cid))
        rec = dict(best, id=cid, first_seen=min(r["first_seen"] for r in g))
        (CONTESTS / f"{cid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if best["id"] in baselines:
            entries[cid] = baselines[best["id"]]
        lines.append(f"{', '.join(r['id'] for r in g[1:])} merged into {cid}"
                     + (f" (content of {best['id']})" if best["id"] != cid else ""))
    up.save_baselines(entries, keep=set(baselines) - set(gone) | set(entries))
    for rid in gone:
        (CONTESTS / f"{rid}.json").unlink(missing_ok=True)
    return lines


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
    cand["tried"] = TODAY
    if result[0] == "record" and not result[2]:
        rid, level = place(result[1], cand, [reader_of(folder)], "single", None)
        cand.update(status="done", record=rid, note=f"single, {level}")
        cand.pop("second", None)  # a new reading of the record: its second reading starts over
        if level == "unverified" and not cand.get("searched"):
            cand.update(status="search", after_search="done")  # no checked deadline or eligibility: look for the rules
        return f"done: {rid} ({level})" + (", to be searched" if cand["status"] == "search" else "")
    if result[0] == "skip":
        cand.update(status="skipped", note=result[1][:200])
        return "skipped: " + result[1][:80]
    return fail_first(cand, describe(result))


def fail_first(cand, note: str) -> str:
    """A first reading that gave nothing usable (attempts already counted)."""
    cand.update(status="failed", note=note)
    if cand["attempts"] >= cq.MAX_ATTEMPTS and cand.get("searched"):
        cand["status"] = "given_up"
    elif cand["attempts"] >= cq.MAX_ATTEMPTS:
        cand.update(status="search", after_search="given_up")
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
    second["tried"] = TODAY
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
        if cand and (cand["status"] in ("new", "failed", "search") or (cand.get("second") or {}).get("attempts", 0) >= cq.MAX_ATTEMPTS):
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


def retry(queue):
    """Read once more, RETRY_DAYS after the last try, what was given up while it may still be open:
    the organizer may have posted its rules since, or its site may be back."""
    before = (date.fromisoformat(TODAY) - timedelta(days=RETRY_DAYS)).isoformat()
    revived = 0
    for c in queue:
        due = c.get("deadline")
        if c.get("record") and (CONTESTS / f"{c['record']}.json").exists():
            due = (entry_deadline(json.loads((CONTESTS / f"{c['record']}.json").read_text(encoding="utf-8"))) or (None,))[0]
        if due and due < TODAY:
            continue
        if c["status"] == "given_up" and not c.get("retried") and c.get("tried", "") <= before:
            c.update(status="new", attempts=0, retried=TODAY)
            revived += 1
        second = c.get("second") or {}
        if second.get("attempts", 0) >= cq.MAX_ATTEMPTS and not second.get("retried") and second.get("tried", "") <= before:
            second.update(attempts=0, retried=TODAY)
            revived += 1
    return revived
