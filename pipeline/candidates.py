"""Keep the queue of contests to read: data/candidates.json.

Run: python3 -I pipeline/candidates.py [<snapshot.md> ...]

Without arguments it reads the newest snapshot of the daily report
($DAILY_REPO/activities/activities-YYYY-MM-DD.md; DAILY_REPO defaults to
~/Projects/tw-highschool-ai-activity-daily). The daily report and this catalogue share
one search: every contest the report found, kept or excluded, comes here with its links.

A candidate is matched to an earlier one by any shared link, so a contest seen again
keeps its place and its status. Statuses:
  new       not read yet
  done      read; `record` names the record
  skipped   read; not a contest this catalogue includes (`note` says why)
  failed    reading failed (`note` says why); tried again up to MAX_ATTEMPTS times
  expired   the deadline in the report had passed before it was read
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data/candidates.json"
DAILY = Path(os.environ.get("DAILY_REPO", Path.home() / "Projects/tw-highschool-ai-activity-daily"))
TODAY = os.environ.get("BUILD_DATE") or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
MAX_ATTEMPTS = 2

LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
BARE = re.compile(r"(?<![(\[])https?://[^\s)|`<>，。」）]+")
ISO = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")
ROLE_OF_FIELD = {"活動辦法": "rules", "報名": "registration", "公告來源": "announcement"}
NOT_DOCUMENTS = ("bhuntr.com/tw/competitions?", "bhuntr.com/tw/competitions)")


def same_url(url: str) -> str:
    """A form of a URL for matching: no scheme, no trailing index.html or slash, host in lower case."""
    url = re.sub(r"^https?://", "", url.strip())
    host, _, rest = url.partition("/")
    rest = re.sub(r"(index\.html?)?/?$", "", rest)
    return f"{host.lower().removeprefix('www.')}/{rest}"


def load():
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []


def save(queue):
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(QUEUE)


def links_in(text: str):
    found = [(name, url) for name, url in LINK.findall(text)]
    rest = LINK.sub(" ", text)
    found += [("", url.rstrip(".,;")) for url in BARE.findall(rest)]
    return [(n, u) for n, u in found if not u.rstrip("/").endswith("bhuntr.com/tw/competitions")]


def clean_title(heading: str) -> str:
    title = re.sub(r"【[^】]*】", "", heading)
    return " ".join(title.replace("🆕", "").split())


def parse_snapshot(path: Path):
    """Contests in one daily snapshot: [{title, deadline, urls, section}]."""
    text = path.read_text(encoding="utf-8")
    out = []
    section = ""
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        if line.startswith("### ") and ("明細" in section or "B 級" in section or "待讀" in section or "候選" in section):
            current = {"title": clean_title(line[4:]), "deadline": None, "urls": [], "section": section}
            out.append(current)
            continue
        if current and line.startswith("- "):
            m = re.match(r"- ([^：:]+)[：:](.*)", line)
            if not m:
                continue
            field, value = m.group(1).strip(), m.group(2)
            if field == "報名截止":
                d = ISO.search(value)
                current["deadline"] = d.group(0) if d else None
            role = ROLE_OF_FIELD.get(field)
            if role:
                for name, url in links_in(value):
                    current["urls"].append({"url": url, "role": role, "name": name})
            continue
        # Tables of excluded contests and of other candidates: | 活動 | 截止日 | … | 公告網址 |
        if line.startswith("|") and ("排除" in section or "候選" in section) and not line.startswith("|---") and not line.startswith("| 活動"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            urls = links_in(cells[-1]) if cells else []
            if urls:
                d = ISO.search(cells[1]) if len(cells) > 1 else None
                out.append({"title": clean_title(cells[0]), "deadline": d.group(0) if d else None,
                            "urls": [{"url": u, "role": "announcement", "name": n} for n, u in urls],
                            "section": section})
    return [c for c in out if c["urls"]]


def merge(queue, found, seen_on):
    by_url = {same_url(u["url"]): c for c in queue for u in c["urls"]}
    added = 0
    for f in found:
        match = next((by_url[same_url(u["url"])] for u in f["urls"] if same_url(u["url"]) in by_url), None)
        if match:
            match["last_seen"] = seen_on
            known = {same_url(u["url"]) for u in match["urls"]}
            for u in f["urls"]:
                if same_url(u["url"]) not in known:
                    match["urls"].append(u)
                    by_url[same_url(u["url"])] = match
            if f["deadline"] and not match.get("deadline"):
                match["deadline"] = f["deadline"]
            continue
        cand = {
            "key": f"c{len(queue) + 1:04d}",
            "title": f["title"],
            "deadline": f["deadline"],
            "urls": f["urls"],
            "seen_in": f["section"],
            "first_seen": seen_on,
            "last_seen": seen_on,
            "status": "new",
            "attempts": 0,
            "record": None,
            "note": None,
        }
        if f["deadline"] and f["deadline"] < TODAY:
            cand["status"] = "expired"
        queue.append(cand)
        for u in f["urls"]:
            by_url[same_url(u["url"])] = cand
        added += 1
    return added


def link_records(queue):
    """Mark candidates whose links already belong to a record. A candidate that reads a record
    again (`record` set by the daily re-check) is left as it is."""
    for path in sorted((ROOT / "data/contests").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        urls = {same_url(u) for u in record_urls(rec)}
        for c in queue:
            if c["status"] in ("new", "failed") and not c.get("record") \
                    and urls & {same_url(u["url"]) for u in c["urls"]}:
                c["status"], c["record"] = "done", rec["id"]


def record_urls(rec) -> set:
    return {rec["links"]["official"], rec["links"]["registration"], *(l["url"] for l in rec["links"]["rules"]),
            *(f["url"] for f in rec["found_via"])} - {None}


def newest_snapshot():
    snaps = sorted((DAILY / "activities").glob("activities-20??-??-??.md"))
    return snaps[-1] if snaps else None


def main():
    paths = [Path(p) for p in sys.argv[1:]] or [newest_snapshot()]
    queue = load()
    for path in paths:
        if not path:
            sys.exit("no snapshot found")
        seen_on = re.search(r"(\d{4}-\d\d-\d\d)", path.name).group(1)
        found = parse_snapshot(path)
        added = merge(queue, found, seen_on)
        print(f"{path.name}: {len(found)} contests with links, {added} new candidates")
    for c in queue:  # a deadline can pass while a candidate waits
        if c["status"] in ("new", "failed") and c.get("deadline") and c["deadline"] < TODAY:
            c["status"] = "expired"
    link_records(queue)
    save(queue)
    counts = {}
    for c in queue:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    print("queue:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
