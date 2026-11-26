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
  first reading says skip                            -> status "skipped"; a record it read again
                                                        moves to data/stale/ (no page) unless "dual"
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
import unicodedata
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
    m = re.search(r"第\s*([0-9０-９]{1,4}|[〇零一二兩三四五六七八九十百]{1,6})\s*[屆届]", edition)
    return cn_number(m.group(1)) if m else None


def years(text: str) -> set:
    """The years a text names, as western years: 「2027」, and 「115 年」 or 「115 學年度」 as 2026."""
    found = {int(y) for y in re.findall(r"(?<!\d)20\d\d(?!\d)", text)}
    return found | {int(y) + 1911 for y in re.findall(r"(?<!\d)1\d\d(?=學?年)", text)}


def same_edition(a, b) -> bool:
    """Organizers reuse a page for the next edition; a shared link alone does not make two readings one record.
    Readers write one edition in several ways (「第 4 屆」 and 「第 4 屆（115 年度）」, 「2027 第五屆」 and
    「第五屆」): where both name an ordinal, the ordinal decides, unless both name years and no year is shared."""
    ea, eb = (re.sub(r"\s+", "", unicodedata.normalize("NFKC", x.get("edition") or "")) for x in (a, b))
    oa, ob = ordinal(ea), ordinal(eb)
    ya, yb = years(ea), years(eb)
    if oa is not None and ob is not None:
        return oa == ob and not (ya and yb and not ya & yb)
    if (oa is None) != (ob is None):  # 「2027」 and 「2027 年第八屆」: the years decide, when the other names only years
        (plain, yp), (ord_side, ord_rec, yo) = ((eb, yb), (ea, a, ya)) if oa is not None else ((ea, ya), (eb, b, yb))
        only_years = r"(?<!\d)20\d\d(?!\d)|1\d\d(?=學?年)|學|年|度|[-–—~～、，,.．()（）]"
        if re.sub(only_years, "", re.sub(r"第([0-9]{1,4}|[〇零一二兩三四五六七八九十百]{1,6})[屆届]", "", ord_side)):
            return False  # 「第 38 屆（秋季）」 is not the whole of 「2026」
        # an edition that names only its ordinal takes the years of its title: 「第 38 屆」 of 「2026第38屆AERC…」
        yo = yo or years(re.sub(r"\s+", "", unicodedata.normalize("NFKC", ord_rec.get("title") or "")))
        return bool(yp) and yp == yo and not re.sub(only_years, "", plain)
    return ea == eb


# a year (2027, 115 年度, 115 學年度) or an ordinal (第七屆) in front of a title, in any order
TITLE_PREFIX = re.compile(r"^(?:(?:20[23]\d(?:學?年度?)?|1\d\d學?年度?|第[0-9一二三四五六七八九十百]+屆)[、，,．.]?)+")
# 「台灣經濟學奧林匹亞」 and 「台灣經濟學奧林匹亞競賽」
TITLE_SUFFIX = re.compile(r"(?:競賽|比賽)$")
# a school year written inside a title: 「經濟學奧林匹亞(EO)2026-2027年校際回合」
TITLE_YEARS = re.compile(r"(?<!\d)20[23]\d[-–—~～]20[23]\d(?!\d)學?年?度?")
# a year anywhere else in a title: 「AERC2026 亞洲機器人運動競技大賽」
TITLE_YEAR = re.compile(r"(?<!\d)(?:20[23]\d(?!\d)(?:學?年度?)?|1\d\d(?:學年度|學年|年度|年))")


def same_contest_by_title(a, b) -> bool:
    """The same title (spaces and letter case aside, a leading year or ordinal and a year anywhere aside:
    「2027 UKMT-IMC」 and 「UKMT-IMC」, 「115 年度綠色化學競賽」 and 「綠色化學競賽」, 「AERC2026 亞洲…」 and
    「2026第38屆AERC亞洲…」, same_edition compares those; and a closing 「競賽」 or 「比賽」 aside) and a shared organizer:
    two readings of one contest whose announcements shared no link."""
    raw = lambda r: re.sub(r"\s+", "", unicodedata.normalize("NFKC", r.get("title") or "")).casefold()
    title = lambda r: TITLE_SUFFIX.sub("", TITLE_YEAR.sub("", TITLE_PREFIX.sub("", TITLE_YEARS.sub("", raw(r)))))
    spans = lambda r: {re.sub(r"\D", "", y)[:8] for y in TITLE_YEARS.findall(raw(r))}
    if spans(a) and spans(b) and not spans(a) & spans(b):
        return False  # 「2026-2027 年」 and 「2027-2028 年」
    orgs = lambda r: {re.sub(r"\s+", "", o.get("name") or "") for o in r.get("organizers") or []} - {"", "unknown"}
    head = lambda r: TITLE_YEARS.sub("", raw(r))
    pa, pb = (TITLE_PREFIX.match(head(r)).group(0) if TITLE_PREFIX.match(head(r)) else "" for r in (a, b))
    if ordinal(pa) is not None and ordinal(pb) is not None and ordinal(pa) != ordinal(pb):
        return False  # 「第七屆…」 and 「第八屆…」
    ya, yb = (years("／".join([p, *TITLE_YEARS.findall(raw(r))])) for p, r in ((pa, a), (pb, b)))
    if ya and yb and not ya & yb:
        return False  # 「115 年度…」 and 「116 年度…」, 「2026-2027年…」 and 「2028年…」
    # a year inside the title: the same years in both (「RX2027」 and 「RX2028」 are models, not years), or in
    # one only and named in front of the other (「AERC2026 亞洲…」 and 「2026第38屆AERC亞洲…」)
    ma, mb = (years("／".join(TITLE_YEAR.findall(TITLE_PREFIX.sub("", head(r))))) for r in (a, b))
    if ma and mb and ma != mb or ma and not mb and not ma <= yb or mb and not ma and not mb <= ya:
        return False
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
        by_title = [o for o in olds if same_contest_by_title(o, rec)]
        match = next((o for o in olds if {cq.same_url(u) for u in cq.record_urls(o)} & cand_urls), None) \
            or (by_title[0] if len(by_title) == 1 else None)  # two records by title: which one is unclear
        if match:
            rec["id"] = match["id"]
    rid = rec["id"]
    path = CONTESTS / f"{rid}.json"
    first_seen = cand.get("first_seen") or TODAY
    joined = None  # the record that a new candidate's reading joins
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if cand.get("record") or same_edition(old, rec) and (
                {cq.same_url(u) for u in cq.record_urls(old)} & cand_urls
                or re.sub(r"\s+", "", old["title"]) == re.sub(r"\s+", "", rec["title"]) or same_contest_by_title(old, rec)):
            first_seen = min(old["first_seen"], first_seen)
            joined = None if cand.get("record") else old
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
    if joined:
        # Another announcement of a contest already recorded (a venue's, a school's): its reading replaces
        # the record only when it is better verified. A school's summary must not replace the full rules.
        old_errors, _, old_level = check(CONTESTS / f"{rid}.json", Cache())
        rank = lambda lv, m: (LEVEL_RANK.get(lv, 3), METHOD_RANK.get(m, 2))
        if not old_errors and rank(old_level, joined["verification"].get("method")) <= rank(level, method):
            cand["joined"] = True  # its documents are not the record's: second_todo reads the record's own
            return rid, old_level
    cand.pop("joined", None)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "data/stale" / f"{rid}.json").unlink(missing_ok=True)  # set aside earlier, read again now
    # What the readers read is what pnpm upstream and the daily re-check compare with.
    up.save_baselines({rid: up.baseline_from_cache(rec)})
    return rid, level


METHOD_RANK = {"dual": 0, "single": 1}
LEVEL_RANK = {"verified": 0, "checked": 1, "unverified": 2}
# Judgements on pairs of records that the rules cannot settle, written by `pnpm daily same` and
# `pnpm daily distinct`: {"same": [[fuller, other], ...], "distinct": [[a, b], ...]}.
JUDGED = ROOT / "data/same-contests.json"


def load_judged() -> dict:
    judged = json.loads(JUDGED.read_text(encoding="utf-8")) if JUDGED.exists() else {}
    return {"same": judged.get("same") or [], "distinct": judged.get("distinct") or []}


def save_judged(judged: dict):
    JUDGED.write_text(json.dumps(judged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def editions_differ(a, b) -> bool:
    """Two editions for certain: two ordinals that differ, or two sets of years with none shared (in the
    edition and the title)."""
    norm = lambda t: re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or "")).casefold()
    ea, eb = (norm(r.get("edition")) + "／" + norm(r.get("title")) for r in (a, b))
    oa, ob, ya, yb = ordinal(ea), ordinal(eb), years(ea), years(eb)
    return oa is not None and ob is not None and oa != ob or bool(ya and yb and not ya & yb)


def merge_duplicates(queue) -> list:
    """Make one record of the records that describe one contest written under two ids before place()
    matched them: the same edition, the same title and a shared organizer (the readers wrote the
    edition differently, or the announcements shared no link), or a pair judged the same contest in
    data/same-contests.json. The id seen first stays, so an address already published stays. Its
    content is the reading the newest judgement names as the fuller one (when that reading was merged
    away already, the kept id's, which holds it), else the best-verified reading, the newest of equals,
    with its baselines; the other ids are removed and their candidates name the id kept. Judgements
    join through each other (A with B and A with C: B with C, when A is gone) and stay after their
    merge: a later reading written under a removed id is merged again. A judgement never joins records
    whose editions differ for certain (editions_differ). The queue is saved before any record changes, so a run stopped halfway finds the same group
    again. Returns lines for the log."""
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTESTS.glob("*.json"))]
    recs.sort(key=lambda r: (r.get("first_seen") or "", bool(re.search(r"-\d+$", r["id"])), r.get("updated") or "", r["id"]))
    groups = []
    for r in recs:
        # every member, not the first only: 「2027」 matches both 「2027 第七屆」 and 「2027 第八屆」
        group = next((g for g in groups if all(same_edition(x, r) and same_contest_by_title(x, r) for x in g)), None)
        group.append(r) if group else groups.append([r])
    order = {r["id"]: i for i, r in enumerate(recs)}
    pairs = load_judged()["same"]
    root = {}  # union-find over every id a judgement names, present or not
    find = lambda x: x if root.setdefault(x, x) == x else find(root[x])
    for x, y in pairs:
        root[find(x)] = find(y)
    lines, judged_groups = [], []
    for cls in {find(x) for x in root}:
        present = [rid for rid in root if find(rid) == cls and rid in order]
        for rid in present[1:]:
            ga, gb = (next(g for g in groups if any(x["id"] == i for x in g)) for i in (present[0], rid))
            if ga is gb:
                continue
            if any(editions_differ(x, y) for x in ga for y in gb):
                lines.append(f"not joined: {present[0]} and {rid} were judged one contest, but their editions differ")
                continue
            groups.remove(gb)
            ga.extend(gb)
            ga.sort(key=lambda r: order[r["id"]])
            judged_groups.append(ga)
    groups = [g for g in groups if len(g) > 1]
    if not groups:
        return lines
    gone = {r["id"]: g[0]["id"] for g in groups for r in g[1:]}
    for c in queue:
        if c.get("record") in gone:
            c["record"] = gone[c["record"]]
    cq.save(queue)
    baselines = (up.load_manifest() or {}).get("records") or {}
    entries = {}
    for g in groups:
        cid = g[0]["id"]
        judged = any(g is j for j in judged_groups)
        best = next((r for fuller, _ in reversed(pairs) for r in g if r["id"] == fuller), None) \
            or (g[0] if judged else None) \
            or min(g, key=lambda r: (METHOD_RANK.get(r["verification"].get("method"), 2),
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


def contest_pages(rec) -> set:
    """The contest's own pages (official, registration, rules), each below a site's root: a site's home
    page or a school's portal serves many contests."""
    links = rec["links"]
    urls = {links.get("official"), links.get("registration"), *(l["url"] for l in links.get("rules") or [])} - {None}
    return {u for u in map(cq.same_url, urls) if u.partition("/")[2]}


def possible_duplicates() -> list:
    """Pairs of records that may describe one contest edition but that the rules of merge_duplicates
    leave apart, and that no judgement in data/same-contests.json settles: they share a contest page,
    or one's title (as same_contest_by_title compares titles) holds the other's and they share an
    organizer, or the titles are the same; and their editions do not differ for certain (editions_differ). Several tracks,
    divisions or stages of a contest share a page, and a stage's title often holds the contest's, so
    such a pair is judged (`pnpm daily same` or `distinct`), not merged. (Two records with the same
    title, edition and organizer are merged by merge_duplicates before this list is made, whatever
    they are.) Returns lines for the log."""
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTESTS.glob("*.json"))]
    judged = load_judged()
    settled = {frozenset(pair) for pair in judged["same"] + judged["distinct"]}
    norm = lambda r: re.sub(r"\s+", "", unicodedata.normalize("NFKC", r.get("title") or "")).casefold()
    title = lambda r: TITLE_SUFFIX.sub("", TITLE_YEAR.sub("", TITLE_PREFIX.sub("", TITLE_YEARS.sub("", norm(r)))))
    orgs = lambda r: {re.sub(r"\s+", "", o.get("name") or "") for o in r.get("organizers") or []} - {"", "unknown"}
    lines = []
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            if frozenset((a["id"], b["id"])) in settled:
                continue
            if editions_differ(a, b):
                continue
            shared = sorted(contest_pages(a) & contest_pages(b))
            ta, tb = sorted((title(a), title(b)), key=len)
            if shared:
                why = f"share {shared[0]}"
            elif len(ta) >= 4 and ta in tb and orgs(a) & orgs(b):
                why = "one title holds the other, a shared organizer"
            elif len(ta) >= 2 and ta == tb:  # an organizer written as its department (「勤益科大電機系」)
                why = "the same title"
            else:
                continue
            lines.append(f"{a['id']} | {b['id']}: {why}")
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
        if cand.get("joined"):  # another announcement of a record better verified: the record stays as it was
            cand.update(status="done", record=rid, note=f"joined {rid}; its reading kept ({level})")
            return f"joined: {rid} ({level}), the record kept"
        cand.update(status="done", record=rid, note=f"single, {level}")
        cand.pop("second", None)  # a new reading of the record: its second reading starts over
        if level == "unverified" and not cand.get("searched"):
            cand.update(status="search", after_search="done")  # no checked deadline or eligibility: look for the rules
        return f"done: {rid} ({level})" + (", to be searched" if cand["status"] == "search" else "")
    if result[0] == "skip":
        cand.update(status="skipped", note=result[1][:200])
        old = CONTESTS / f"{cand.get('record')}.json"
        # a record read again and found not to be a contest loses its page, unless two readings agreed on it
        if cand.get("record") and old.exists() and json.loads(old.read_text(encoding="utf-8"))["verification"].get("method") != "dual":
            target = ROOT / "data/stale" / old.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(old, target)
            baselines = (up.load_manifest() or {}).get("records") or {}
            up.save_baselines({}, keep=set(baselines) - {cand["record"]})
            return f"skipped, {cand['record']} set aside: " + result[1][:80]
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
    # a candidate that only joined a record (extract.place) does not read it: its documents are another's
    by_record = {c["record"]: c for c in queue if c.get("record") and not c.get("joined")}
    pending = {c["record"] for c in queue if c.get("record") and c["status"] in ("new", "failed", "search")}
    todo = []
    for path in sorted(CONTESTS.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        due = entry_deadline(rec)
        v = rec["verification"]
        if v["method"] != "single" or len(v.get("readers") or []) >= 2 or (due and passed(due)):
            continue  # a second reading that left a key fact unconfirmed keeps the record single
        cand = by_record.get(rec["id"])
        if rec["id"] in pending or cand and (cand.get("second") or {}).get("attempts", 0) >= cq.MAX_ATTEMPTS:
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
