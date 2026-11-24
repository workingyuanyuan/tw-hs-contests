"""Read the list pages of the sources and record every announcement on them.

Run: uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/discover.py [--source ID ...] [--dry-run]

The sources are in data/sources.json, one entry each:
  id, name, url    the list page
  read             "html" (fetch, render when the page has almost no text), "render" (always in a
                   browser), or "rss" (an RSS feed: title, link and pubDate of each item)
  item             regular expression an announcement's address matches (searched in the full URL)
  pages            address of page n, with {n} in it (null: one page)
  start            the number of the list page itself (default 1); page n after it is read from
                   "pages". A list page that holds what the first pages of "pages" hold (a page of the
                   latest 100 posts in front of a category archive of 30 a page) sets "start" to the
                   first archive page it does not cover, so a daily run reads one page and a first run
                   goes on in the archive
  max_pages        pages to read at most in one run, the list page included
  scrolls          times at most to scroll a rendered list to the bottom (lists that load as you scroll)
  date             where the list prints an announcement's date: omitted, on the title's line, else
                   the line before, else the line after; "before", the nearest date in the lines above
                   the title, back to the previous announcement; "after", the nearest date below it, up
                   to the next announcement; "url", only the date in the announcement's address. Dates
                   inside a title are never read (they are dates of the event, not of the
                   announcement), nor dates after today; with no date by the title, the date in the
                   address is used.
  note             how the source behaves, in a sentence

Each announcement goes into data/discovered.json, keyed by its address, with its title, the date
next to it on the list (when the list shows one), the sources it was seen on and an outcome:
  new       not looked at yet
  excluded  the title shows it is not a contest (EXCLUDE names the word)
pipeline/triage.py changes the outcome later:
  queued       a candidate in data/candidates.json (note: its key)
  duplicate    the address belongs to a record already (note: the record)
  not_contest  a triage task judged the title not a contest (note: why)

A source is read page by page until one of these, which the run records as its stop reason:
  seen   a whole page of announcements already in data/discovered.json
  old    the newest date on a page is more than OLD_DAYS days before today
  end    no more pages: the source has one page, a page holds no announcement not already read
         (sites repeat the last page past the end), or a page after the first answers 404
  max    max_pages read while the page still held new, recent announcements: status partial
  error  a page could not be read: status failed (partial when page 1 was read)
Pages of one source are read one after another, at least a second apart.
A source whose first page gives no announcement at all, or far fewer than the last run, is failed:
the page or its markup changed, not the source's activity.

The run writes, per source, the pages read, the announcements seen and new, the oldest date seen
and the stop reason to data/runs/<date>.json under "discover".
"""
import argparse
import html as htmllib
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402
from candidates import TODAY, same_url  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data/sources.json"
DISCOVERED = ROOT / "data/discovered.json"
RUNS = ROOT / "data/runs"
OLD_DAYS = 120
MIN_TITLE = 6
PAUSE = 1.0  # seconds at least between two pages of one source
# A title with one of these is not a contest announcement. Only words that never name a contest:
# results, admissions, procurement, staff, scholarships. Camps, lectures and exams are left to the
# reader, because some of them hold a judged contest.
EXCLUDE = re.compile(
    r"【賀】|賀[!！：:]|^賀|恭賀|榮獲|榮登|獲獎|得獎名單|得獎公告|得獎作品|獲獎名單|成績公告|錄取名單|榜單|放榜"
    r"|招生|招標|採購|標案|甄選.{0,6}教師|教師甄|代理教師|代課|職缺|徵才|約聘|人事|停課|停班"
    r"|獎學金|助學金|助學|補助申請|交通車|午餐|健康檢查|防疫|校外教學|家長日|親師")
DATE_PATTERNS = [
    re.compile(r"(?<!\d)(20\d\d)[-/.年](\d{1,2})[-/.月](\d{1,2})"),
    re.compile(r"(?<!\d)(1[01]\d)[-/.年](\d{1,2})[-/.月](\d{1,2})"),  # ROC year
    re.compile(r"/(20\d\d)/(\d\d)/(\d\d)/"),
    re.compile(r"/(20\d\d)(\d\d)(\d\d)(?:/|\.aspx)"),
]


def find_date(*texts):
    for text in texts:
        for pat in DATE_PATTERNS:
            for m in pat.finditer(text or ""):
                y, mo, d = (int(g) for g in m.groups())
                if y < 1000:
                    y += 1911
                try:
                    return date(y, mo, d).isoformat()
                except ValueError:
                    continue
    return None


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def rss_items(url):
    body, ctype, status = fetch.http_get(url)
    if status >= 400:
        raise fetch.FetchError(f"HTTP {status}")
    text = body.decode("utf-8", errors="replace")  # feeds that declare another encoding are UTF-8
    items = []
    for block in re.findall(r"<item\b.*?</item>", text, re.S | re.I):
        def tag(name, block=block):
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S | re.I)
            return htmllib.unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S)).strip() if m else ""
        items.append({"title": " ".join(tag("title").split()), "url": tag("link"),
                      "date": find_date(tag("pubDate"), tag("dc:date"))})
        if items[-1]["date"] is None and tag("pubDate"):
            from email.utils import parsedate_to_datetime  # noqa: PLC0415
            try:
                items[-1]["date"] = parsedate_to_datetime(tag("pubDate")).date().isoformat()
            except (TypeError, ValueError):
                pass
    return items


def page_items(src, url):
    """Announcements on one list page: [{title, url, date}]."""
    if src["read"] == "rss":
        return rss_items(url)
    if src["read"] == "render" or src.get("scrolls"):
        text, links = fetch.browser_text(url, scrolls=src.get("scrolls", 0))
    else:
        _, text, links, _ = fetch.read(url)
    pattern = re.compile(src["item"])
    items, seen = [], set()
    for link in links:
        title = " ".join(link["text"].split())
        if len(title) < MIN_TITLE or not pattern.search(link["url"]):
            continue
        key = same_url(link["url"])
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "url": link["url"], "date": None})
    lines = [" ".join(line.split()) for line in text.splitlines()]
    titles = sorted({it["title"] for it in items}, key=len, reverse=True)

    def bare(i):
        """Line i without the titles in it, so that a date inside a title is not read."""
        line = lines[i]
        for t in titles:
            line = line.replace(t, " ")
        return line

    where = src.get("date")
    ats, prev = [], 0
    for it in items:  # the list text runs in the order of the links
        ats.append(title_line(lines, it["title"], prev))
        prev = ats[-1] + 1 if ats[-1] is not None else prev
    marks = sorted({a for a in ats if a is not None})
    for it, at in zip(items, ats):
        near = []
        if at is not None and where != "url":
            if where == "before":
                stop = max([m for m in marks if m < at] or [at - 13])
                near = [at] + list(range(at - 1, max(stop, -1), -1))
            elif where == "after":
                stop = min([m for m in marks if m > at] or [at + 13])
                near = [at] + list(range(at + 1, min(stop, len(lines))))
            else:
                near = [i for i in (at, at - 1, at + 1) if 0 <= i < len(lines)]
        it["date"] = find_date(*(bare(i) for i in near), it["url"])
        if it["date"] and it["date"] > TODAY:  # a deadline next to the title, not the day it was posted
            it["date"] = None
    return items


def title_line(lines, title, start=0):
    """Index of the line of the list text that shows this title, or None. Tried in order: the whole
    title, its start, a line that cuts the title short ("2026育網盃全國高中..."), then its end (a link
    whose text runs over several lines, such as a date line and a title line). Each test looks from
    line `start` on (the line after the previous announcement), then above it."""
    def stem_of(line):
        stem = line.rstrip(".…· ")
        return len(stem) >= 8 and stem != line and title.startswith(stem)

    tests = [lambda line: title in line, lambda line: title[:20] in line, stem_of,
             lambda line: title[-20:] in line, lambda line: title[-10:] in line]
    order = list(range(start, len(lines))) + list(range(min(start, len(lines))))
    for test in tests:
        for i in order:
            if test(lines[i]):
                return i
    return None


def page_url(src, n):
    if n == src.get("start", 1):
        return src["url"]
    return src["pages"].format(n=n)


def read_source(src, discovered, last_count):
    """Read one source. Returns (ledger entry, items)."""
    today = date.fromisoformat(TODAY)
    old = (today - timedelta(days=OLD_DAYS)).isoformat()
    entry = {"name": src["name"], "pages": 0, "seen": 0, "new": 0, "oldest": None, "stop": None,
             "status": "ok"}
    found = []
    first = src.get("start", 1)
    last = first + (src.get("max_pages", 1) - 1 if src.get("pages") else 0)
    for n in range(first, last + 1):
        if n > first:
            time.sleep(PAUSE)
        try:
            items = page_items(src, page_url(src, n))
        except Exception as e:  # noqa: BLE001  one source failing does not stop the run
            if n > first and "HTTP 404" in str(e):
                entry["stop"] = "end"  # past the last page
                break
            entry["stop"], entry["error"] = "error", f"page {n}: {type(e).__name__}: {str(e)[:160]}"
            entry["status"] = "partial" if entry["pages"] else "failed"
            break
        entry["pages"] += 1
        fresh = [it for it in items if it["url"] not in {f["url"] for f in found}]
        if n == first:
            entry["first_page"] = len(fresh)
        if n == first and not fresh:
            entry["stop"], entry["status"] = "end", "failed"
            entry["error"] = "no announcement on the first page"
            break
        if not fresh:
            entry["stop"] = "end"  # a page past the last one repeats the last page or is empty
            break
        found += fresh
        dates = [it["date"] for it in fresh if it["date"]]
        if dates:
            entry["oldest"] = min([entry["oldest"] or dates[0], *dates])
        unseen = [it for it in fresh if same_url(it["url"]) not in discovered]
        if not unseen and discovered:
            entry["stop"] = "seen"
            break
        if dates and max(dates) < old:
            entry["stop"] = "old"
            break
        if not src.get("pages"):
            entry["stop"] = "end"
            break
    else:
        entry["stop"], entry["status"] = "max", "partial"
    entry["seen"] = len(found)
    if entry["status"] == "ok" and last_count and entry.get("first_page", 0) < 0.3 * last_count:
        entry["status"] = "failed"
        entry["error"] = f"{entry['first_page']} announcements on page 1, {last_count} in the last run"
    return entry, found


def record(discovered, src, items, today):
    new = 0
    for it in items:
        key = same_url(it["url"])
        cur = discovered.get(key)
        if cur:
            cur["last_seen"] = today
            if src["id"] not in cur["sources"]:
                cur["sources"].append(src["id"])
            continue
        m = EXCLUDE.search(it["title"])
        discovered[key] = {"url": it["url"], "title": it["title"], "date": it["date"], "sources": [src["id"]],
                           "first_seen": today, "last_seen": today,
                           "outcome": "excluded" if m else "new", "note": f"title: {m.group(0)}" if m else None}
        new += 0 if m else 1
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", default=[], help="read only these source ids")
    ap.add_argument("--dry-run", action="store_true", help="print what was found; write nothing")
    args = ap.parse_args()
    sources = [s for s in load_json(SOURCES, []) if not args.source or s["id"] in args.source]
    discovered = load_json(DISCOVERED, {})
    run_path = RUNS / f"{TODAY}.json"
    run = load_json(run_path, {"date": TODAY})
    last = {}
    for path in sorted(RUNS.glob("20??-??-??.json"))[::-1]:
        if path != run_path:
            last = load_json(path, {}).get("discover", {})
            if last:
                break
    ledger = {}
    for src in sources:
        known = {k: v for k, v in discovered.items() if src["id"] in v["sources"]}
        entry, items = read_source(src, known, (last.get(src["id"]) or {}).get("first_page"))
        if args.dry_run:
            entry["new"] = sum(1 for it in items if same_url(it["url"]) not in discovered)
            print(f"{src['id']:<14} {entry['status']:<8} pages {entry['pages']:>2}  seen {entry['seen']:>3}  "
                  f"new {entry['new']:>3}  oldest {entry['oldest']}  stop {entry['stop']}  {entry.get('error', '')}")
            for it in items[:3]:
                print(f"    {it['date']}  {it['title'][:60]}")
        else:
            entry["new"] = record(discovered, src, items, TODAY)
            print(f"{src['id']}: {entry['status']}, {entry['seen']} seen, {entry['new']} new, stop {entry['stop']}"
                  + (f" ({entry['error']})" if entry.get("error") else ""))
        ledger[src["id"]] = entry
    if args.dry_run:
        return
    save_json(DISCOVERED, dict(sorted(discovered.items(), key=lambda kv: (kv[1]["first_seen"], kv[0]))))
    run["discover"] = {**run.get("discover", {}), **ledger}
    save_json(run_path, run)
    failed = [k for k, v in ledger.items() if v["status"] == "failed"]
    print(f"{len(ledger)} sources, {sum(v['new'] for v in ledger.values())} new announcements"
          + (f"; failed: {', '.join(failed)}" if failed else ""))


if __name__ == "__main__":
    main()
