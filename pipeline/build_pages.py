"""Write the generated pages and data files from data/contests/*.json.

Run: uv run -q --isolated --with jsonschema python -I pipeline/build_pages.py

Writes, replacing what was there:
  src/content/docs/index.md              home page
  src/content/docs/contests/<id>.md      one page per contest edition
  src/content/docs/deadlines/<yyyy-mm>.md   open contests by deadline month
  src/content/docs/subjects/<slug>.md       open contests by subject
  src/content/docs/archive/<yyyy-mm>.md     closed contests (the contest pages keep their address)
  public/data/contests.json, public/data/contests/<id>.json

A record with an error is left out and named on stderr; the exit code is then 1.
A record whose key facts are not checked gets no page: it is in contests.json only.
Pages show the contest: what to do, the deadline, who may enter, prizes, timeline, and a fee
only when one is charged. Attendance, AI rules and the quotes stay in the data files, which
the private daily report reads; they are not the catalogue's business.
A contest is open while a new entrant can still register (validate.entry_deadline); after
that it moves to the archive.
There are no hand-written pages.
"""
import json
import re
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import ROOT, Cache, check, entry_deadline, passed  # noqa: E402

SITE = os.environ.get("SITE_URL", "https://yuanaruru.com/tw-hs-contests").rstrip("/")
DOCS = ROOT / "src/content/docs"
DATA_OUT = ROOT / "public/data"
DATA_URL = f"{SITE}/data/contests.json"
TODAY = os.environ.get("BUILD_DATE") or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
INDEX_CAVEAT = "截止日指新參賽者報名的最後一天，以臺灣時間計。"
ARCHIVE_CAVEAT = "下一屆的日期以主辦單位的公告為準。"

SUBJECT_SLUGS = {
    "資訊與 AI": "ai-and-computing", "自然科學": "science", "數學": "math", "語文與寫作": "language-and-writing",
    "外語": "foreign-languages", "社會人文": "humanities", "商管與行銷": "business", "創業與企劃": "entrepreneurship",
    "設計": "design", "美術": "fine-arts", "影音": "video", "音樂": "music", "表演藝術": "performing-arts",
    "體育": "sports", "技藝與技能": "skills", "餐旅": "hospitality", "工程與製造": "engineering",
    "農業與環境": "agriculture-and-environment", "醫護與照顧": "health-and-care", "其他": "other",
}
DIVISION_TEXT = {"hs_only": "只限高中職學生", "separate": "高中職自成一組", "mixed": "高中職與其他對象同組評比"}
HOW_TEXT = {"online": "線上繳交", "mail": "郵寄或親送", "onsite": "現場", "unknown": ""}
HOME_ROWS = 8  # contests in the list on the home page; more push the index links past 5,000 characters
SOON_DAYS = 14  # "closing soon" on the home page


def ystr(text) -> str:
    """A YAML double-quoted string."""
    return json.dumps(str(text), ensure_ascii=False)


def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def quote_md(text: str) -> str:
    for ch in "\\*_`<":
        text = text.replace(ch, "\\" + ch)
    return "> " + " ".join(text.split())


def frontmatter(fields: dict, sources: list) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {ystr(v)}" for k, v in value.items()]
        else:
            lines.append(f"{key}: {value if key == 'lastVerified' else ystr(value)}")
    lines.append("sources:")
    for s in sources:
        lines += [f"  - title: {ystr(s['title'])}", f"    url: {ystr(s['url'])}"]
    return "\n".join(lines + ["---", ""])


def deadline(rec):
    """The last day a new entrant can join, as (date, time); None when unknown."""
    return entry_deadline(rec)


def is_open(rec) -> bool:
    d = deadline(rec)
    return d is None or not passed(d)


def deadline_text(rec) -> str:
    d = deadline(rec)
    return "" if not d else f"{d[0]} {d[1]}".strip()




def organizers(rec) -> str:
    hosts = [o["name"] for o in rec["organizers"] if o["role"] == "主辦"] or [rec["organizers"][0]["name"]]
    return "、".join(hosts)


def fee_text(rec) -> str:
    """A fee is shown only when one is charged."""
    f = rec["fee"]
    if f["value"] not in ("required", "deposit"):
        return ""
    label = {"required": "須繳報名費", "deposit": "須繳保證金"}[f["value"]]
    return f["amount"] or label


def levels_text(levels) -> str:
    names = list(levels)
    if "高中" in names and "高職" in names:
        names[names.index("高中")] = "高中職"
        names.remove("高職")
    return "、".join(names)


# A region named as who enters ("臺北市國小至高中職學生"), not as a subject ("以臺北市為主題").
REGION_WHO = r"(?:的|各|轄內|所屬|公私立)*(?:國小|國中|高中|高職|五專|大專|大學|學生|在學|在籍|設籍)"


def caveat(rec) -> str:
    """The one qualifier a reader most likely misses, as a sentence that stands alone."""
    e, f = rec["eligibility"], rec["fee"]
    if not is_open(rec):
        main = f"報名已於 {deadline_text(rec)} 截止。"
    elif e["nomination"] == "school":
        main = "須由學校推薦或薦送，學生不能自行報名。"
    elif e["regions"] and e["regions"] != ["全國"] and not all(re.search(re.escape(r) + REGION_WHO, rec["summary"]) for r in e["regions"]):
        # an answer line that limits who enters to the regions already says it; the next qualifier is the caveat
        main = f"只限{'、'.join(e['regions'])}的學生參加。"
    elif e["division"] == "mixed":
        main = "高中職學生與大專生或社會人士同組評比。"
    elif f["value"] in ("required", "deposit"):
        main = f"報名須繳費：{f['amount']}。" if f["amount"] else "報名須繳費。"
    elif rec.get("conflict"):
        return rec["conflict"]
    else:
        main = "日期與時間都是臺灣時間。"
    return main + (rec.get("conflict") or "")


def source_titles(rec) -> dict:
    titles = {}
    for f in rec["found_via"]:
        if f["url"]:
            titles.setdefault(f["url"], f"轉發公告：{f['name']}")
    for link in rec["links"]["rules"]:
        titles[link["url"]] = link["title"]
    if rec["links"]["registration"]:
        titles[rec["links"]["registration"]] = "報名頁面"
    if rec["links"]["official"]:
        titles[rec["links"]["official"]] = "官方頁面"
    # A cached page may be the official page under a longer address (index.html); another page
    # under the official address is a source of its own and keeps its path.
    official = rec["links"]["official"]
    for fact in facts_of(rec):
        for ev in fact["evidence"]:
            if ev["url"] not in titles:
                rest = ev["url"][len(official):].strip("/") if official and ev["url"].startswith(official) else None
                if rest in ("", "index.html", "index.htm", "index.php"):
                    titles[ev["url"]] = "官方頁面"
                elif rest is not None:
                    titles[ev["url"]] = "官方網站其他頁面"
                else:
                    titles[ev["url"]] = urlparse(ev["url"]).netloc
    return titles


def facts_of(rec):
    return [rec["eligibility"], *rec["dates"], rec["attendance"], rec["fee"], rec["prizes"], rec["ai_policy"]]


def contest_sources(rec) -> list:
    titles = source_titles(rec)
    seen, out = set(), []
    order = [rec["links"]["official"], rec["links"]["registration"], *(l["url"] for l in rec["links"]["rules"])]
    order += [ev["url"] for fact in facts_of(rec) for ev in fact["evidence"]]
    order += [f["url"] for f in rec["found_via"]]
    for url in order:
        if url and url not in seen and not (titles[url] == "官方頁面" and any(s["title"] == "官方頁面" for s in out)):
            seen.add(url)
            out.append({"title": titles[url], "url": url})
    if not out:
        out = [{"title": f["name"], "url": f["url"]} for f in rec["found_via"] if f["url"]]
    return out


def shared_titles(records) -> set:
    """Names that more than one contest page would carry: one contest in two editions. Each page
    needs a title of its own (scripts/check-found.mjs), so those pages add the edition."""
    names = [r["title"] for r in records]
    return {name for name in names if names.count(name) > 1}


def contest_page(rec, linked_subjects=frozenset(SUBJECT_SLUGS), shared=frozenset()) -> str:
    """`linked_subjects`: subjects that have a page (a subject page lists open contests only)."""
    e = rec["eligibility"]
    who = levels_text(e["levels"])
    if e["division"] in DIVISION_TEXT:
        who += f"；{DIVISION_TEXT[e['division']]}"
    parts = []
    if e["team_min"] and e["team_max"]:
        parts.append(f"{e['team_min']} 人" if e["team_min"] == e["team_max"] else f"{e['team_min']} 至 {e['team_max']} 人")
    teacher = {"required": "須有指導老師", "optional": "可有指導老師", "none": "不設指導老師", "unknown": ""}[e["teacher"]]
    if teacher:
        parts.append(teacher)
    when = deadline_text(rec)
    if when and not is_open(rec):
        when += "（已截止）"
    rows = [
        ("報名截止", when),
        ("參賽對象", who),
        ("地區", "、".join(e["regions"])),
        ("報名方式", "須由學校推薦或薦送" if e["nomination"] == "school" else ""),
        ("隊伍", "；".join(parts)),
        ("費用", fee_text(rec)),
        ("主辦", organizers(rec)),
        ("類別", "、".join(f"[{c}](/subjects/{SUBJECT_SLUGS[c]}/)" if c in linked_subjects else c for c in rec["categories"])),
    ]
    rows = [(k, v) for k, v in rows if v]
    body = ["## 重點", "", "| 項目 | 內容 |", "| --- | --- |"]
    body += [f"| {k} | {cell(v)} |" for k, v in rows]

    if rec["deliverables"]:
        body += ["", "## 要交什麼", ""]
        for x in rec["deliverables"]:
            how = f"（{HOW_TEXT[x['how']]}）" if HOW_TEXT[x["how"]] else ""
            body.append(f"- {x['stage']}：{x['what']}{how}")

    if rec["prizes"]["text"]:
        body += ["", "## 獎項", "", rec["prizes"]["text"]]

    dated = sorted((d for d in rec["dates"] if d["date"]), key=lambda d: (d["date"], d["time"] or ""))
    if dated:
        # A conflict between the organizer's documents is in the caveat (page notes); one fact appears once.
        body += ["", "## 時程", "", "| 日期 | 事項 |", "| --- | --- |"]
        body += [f"| {d['date']} {d['time'] or ''} | {cell(d['label'])} |".replace("  |", " |") for d in dated]

    fields = {
        "title": f"{rec['title']}（{rec['edition']}）" if rec["title"] in shared else rec["title"],
        "description": rec["summary"],
        "appliesTo": f"{rec['edition']} 這一屆",
        "caveat": caveat(rec),
        "lastVerified": rec["verification"]["last_verified"] or rec["updated"],
        "kind": "contest",
    }
    if deadline(rec):
        fields["deadline"] = deadline(rec)[0]
    return frontmatter(fields, contest_sources(rec)) + "\n" + "\n".join(body) + "\n"


def contest_table(items, short=False) -> list:
    """Rows sorted by deadline; contests without a known deadline come last. A full list has three
    columns (deadline, contest with its summary, who may enter): the only tables of three columns,
    which the skin (src/styles/site.css) styles by that. A short list (home page) has two."""
    rows = ["| 截止日 | 比賽 |", "| --- | --- |"] if short else ["| 截止日 | 比賽 | 參賽對象 |", "| --- | --- | --- |"]
    for rec in sorted(items, key=lambda r: (deadline(r) or ("9999", ""), r["id"])):
        link = f"[{cell(rec['title'])}](/contests/{rec['id']}/)"
        if short:
            rows.append(f"| {deadline_text(rec)} | {link} |")
        else:
            rows.append(f"| {deadline_text(rec)} | {link} {cell(rec['summary'])} | {cell(levels_text(rec['eligibility']['levels']))} |")
    return rows


def first_last(items, which: str) -> str:
    """The answer line of an index page: how many, and the earliest or latest deadline."""
    dates = sorted(deadline_text(r) for r in items if deadline(r))
    if not dates:
        return f"{len(items)} 則，截止日未定。"
    return f"{len(items)} 則，{which}在 {dates[0] if which == '最早' else dates[-1]} 截止。"


def last_checked(items) -> str:
    return max(r["verification"]["last_verified"] or r["updated"] for r in items)


def index_page(title, label, description, applies, items, caveat_text=INDEX_CAVEAT) -> str:
    fields = {"title": title, "description": description, "appliesTo": applies, "caveat": caveat_text,
              "lastVerified": last_checked(items), "kind": "index", "sidebar": {"label": label}}
    body = contest_table(items)
    return frontmatter(fields, [{"title": "所有比賽的完整資料", "url": DATA_URL}]) + "\n" + "\n".join(body) + "\n"


def home_page(records, months, subjects, archive) -> str:
    live = [r for r in records if is_open(r)]
    soon_end = (datetime.fromisoformat(TODAY) + timedelta(days=SOON_DAYS)).date().isoformat()
    soon = [r for r in live if deadline(r) and deadline(r)[0] <= soon_end]
    fields = {
        "title": "高中職競賽目錄",
        "description": f"臺灣高中職學生現在可以報名的比賽 {len(live)} 則，{len(soon)} 則在 {SOON_DAYS} 天內截止。",
        "appliesTo": f"資料更新至 {last_checked(records)}",
        "caveat": "日期皆為臺灣時間 (UTC+8)；截止日是新參賽者報名的最後一天。",
        "lastVerified": last_checked(records),
        "kind": "page",
    }
    body = [f"## 即將截止（{SOON_DAYS} 天內）", ""]
    # The home lists are short (date and name): the home page must reach every other page within the
    # first 5,000 characters an agent's fetch returns (scripts/check-dist.mjs). Columns go before pages.
    body += contest_table(soon[:HOME_ROWS], short=True) if soon else [f"{soon_end} 之前沒有截止的比賽。"]
    body += ["", "## 截止月份", ""]
    body += [f"- [{m[:4]} 年 {int(m[5:])} 月](/deadlines/{m}/)：{len(items)} 則" for m, items in sorted(months.items()) if m != "undated"]
    if "undated" in months:
        body.append(f"- [截止日未定](/deadlines/undated/)：{len(months['undated'])} 則")
    body += ["", "## 類別", ""]
    body += [f"- [{name}](/subjects/{SUBJECT_SLUGS[name]}/)：{len(items)} 則" for name, items in subjects.items()]
    if archive:
        body += ["", "## 封存", ""]
        body += [f"- [{m[:4]} 年 {int(m[5:])} 月截止](/archive/{m}/)：{len(items)} 則" for m, items in sorted(archive.items(), reverse=True)]
    return frontmatter(fields, [{"title": "所有比賽的完整資料", "url": DATA_URL}]) + "\n" + "\n".join(body) + "\n"


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main():
    cache = Cache()
    records, rejected = [], []
    for path in sorted((ROOT / "data/contests").glob("*.json")):
        errors, _, level = check(path, cache)
        if errors:
            rejected.append((path.name, errors))
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        # Every document a fact rests on is in the page's sources (../AGENTS.md, Content contract).
        listed = {s["url"] for s in contest_sources(rec)}
        missing = sorted({ev["url"] for fact in facts_of(rec) for ev in fact["evidence"]} - listed)
        if missing:
            rejected.append((path.name, [f"evidence not in the page's sources: {missing[0]}"]))
            continue
        rec["_level"] = level
        records.append(rec)
    if not records:
        sys.exit("no record passed the checks; nothing written")

    for folder in ("contests", "deadlines", "subjects", "archive"):
        shutil.rmtree(DOCS / folder, ignore_errors=True)
    shutil.rmtree(DATA_OUT, ignore_errors=True)

    months, subjects, archive = {}, {}, {}
    public = []
    paged = []
    for rec in records:
        level = rec.pop("_level")
        if level == "unverified":
            out = {**rec, "level": level, "url": None, "markdown": None}
            public.append(out)
            write(DATA_OUT / "contests" / f"{rec['id']}.json", json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            continue
        paged.append(rec)
        d = deadline(rec)
        if not is_open(rec):
            archive.setdefault(d[0][:7], []).append(rec)
        else:
            months.setdefault(d[0][:7] if d else "undated", []).append(rec)
            for c in rec["categories"]:
                subjects.setdefault(c, []).append(rec)
        out = {**rec, "level": level, "url": f"{SITE}/contests/{rec['id']}/", "markdown": f"{SITE}/contests/{rec['id']}.md"}
        public.append(out)
        write(DATA_OUT / "contests" / f"{rec['id']}.json", json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    subjects = {name: subjects[name] for name in SUBJECT_SLUGS if name in subjects}
    shared = shared_titles(paged)
    for rec in paged:
        write(DOCS / "contests" / f"{rec['id']}.md", contest_page(rec, set(subjects), shared))

    for m, items in months.items():
        if m == "undated":
            page = index_page("截止日未定的比賽", "截止日未定", f"截止日未定的比賽 {len(items)} 則，主辦單位尚未公布截止日。",
                              f"資料更新至 {last_checked(items)}", items)
        else:
            name = f"{m[:4]} 年 {int(m[5:])} 月"
            page = index_page(f"{name}截止的比賽", name, f"{name}截止的比賽 " + first_last(items, "最早"),
                              f"資料更新至 {last_checked(items)}", items)
        write(DOCS / "deadlines" / f"{m}.md", page)
    for m, items in archive.items():
        name = f"{m[:4]} 年 {int(m[5:])} 月"
        write(DOCS / "archive" / f"{m}.md",
              index_page(f"{name}截止的比賽（封存）", f"{name}截止", f"{name}已截止的比賽 " + first_last(items, "最晚"),
                         f"資料更新至 {last_checked(items)}", items, ARCHIVE_CAVEAT))
    for name, items in subjects.items():
        write(DOCS / "subjects" / f"{SUBJECT_SLUGS[name]}.md",
              index_page(f"類別：{name}", name, f"{name}類的比賽 " + first_last(items, "最早"),
                         f"資料更新至 {last_checked(items)}", items))
    write(DOCS / "index.md", home_page(paged, months, subjects, archive))
    write(DATA_OUT / "contests.json", json.dumps(
        {"site": SITE, "generated": TODAY, "timezone": "Asia/Taipei", "count": len(public), "contests": public},
        ensure_ascii=False, indent=2) + "\n")

    print(f"{len(paged)} contest pages ({len(records) - len(paged)} records without a page), {len(months)} deadline pages, "
          f"{len(subjects)} subject pages, {len(archive)} archive pages written")
    for name, errors in rejected:
        print(f"left out: {name}: {errors[0]}", file=sys.stderr)
    sys.exit(1 if rejected else 0)


if __name__ == "__main__":
    main()
