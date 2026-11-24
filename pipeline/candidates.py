"""The queue of contests to read: data/candidates.json.

Candidates come from discovery (pipeline/triage.py groups the announcements that name one contest)
and from the daily re-check (a record whose documents changed is read again under its id). A
candidate is matched to an earlier one by any shared link, so a contest seen again keeps its place
and its status. Statuses:
  new       not read yet
  done      read; `record` names the record
  skipped   read; not a contest this catalogue includes (`note` says why)
  failed    reading failed (`note` says why); tried again up to MAX_ATTEMPTS times
  search    to be searched for once (pipeline/search.py): its documents could not be fetched, its
            readings failed MAX_ATTEMPTS times, or its record lacks a checked deadline or eligibility
  given_up  failed after the search too; read once more a week later while it may be open
  expired   the deadline known before reading had passed before it was read
Other fields: `need` (links the reader asked for, given at its next reading), `second` (the second
reading of its record: attempts, need, note, tried, retried), `tried` (the day of the last reading),
`searched` (the day of its search), `retried` (the day it was given another try).
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data/candidates.json"
TODAY = os.environ.get("BUILD_DATE") or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
MAX_ATTEMPTS = 2


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


def next_key(queue) -> str:
    numbers = [int(c["key"][1:]) for c in queue if re.fullmatch(r"c\d+", c["key"])]
    return f"c{max(numbers, default=0) + 1:04d}"


def expire(queue):
    """A deadline can pass while a candidate waits."""
    for c in queue:
        if c["status"] in ("new", "failed", "search") and not c.get("record") and c.get("deadline") and c["deadline"] < TODAY:
            c["status"] = "expired"


def link_records(queue):
    """Mark candidates whose links already belong to an open record. A candidate that reads a record
    again (`record` set by the daily re-check) is left as it is. A closed record is not matched: its
    organizer may reuse the page for the next edition, which is read as a record of its own."""
    from validate import entry_deadline, passed  # noqa: PLC0415  (needs jsonschema, which the pipeline has)

    for path in sorted((ROOT / "data/contests").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        due = entry_deadline(rec)
        if due and passed(due):
            continue
        urls = {same_url(u) for u in record_urls(rec)}
        for c in queue:
            if c["status"] in ("new", "failed") and not c.get("record") \
                    and urls & {same_url(u["url"]) for u in c["urls"]}:
                c["status"], c["record"] = "done", rec["id"]


def record_urls(rec) -> set:
    return {rec["links"]["official"], rec["links"]["registration"], *(l["url"] for l in rec["links"]["rules"]),
            *(f["url"] for f in rec["found_via"])} - {None}
