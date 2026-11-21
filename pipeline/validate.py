"""Check every record in data/contests/ and report its verification level.

Run: uv run --isolated --with jsonschema python -I pipeline/validate.py

The level is computed here, never written by the agent that extracted the record:
  (key facts: the deadline and who may enter)
  verified    key facts pass the checks and two independent readings agreed
  checked     key facts pass the checks, one reading
  unverified  at least one key fact has no checked support, or two readings disagreed

Exit code 1 when any record has an error.
"""
import json
import re
import sys
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
# The facts a page needs. Attendance and fee are checked when given and left off the page when unknown.
KEY_FACTS = ("deadline", "eligibility")
SCHEMA = json.loads((ROOT / "data/schema/contest.schema.json").read_text(encoding="utf-8"))
CACHE = ROOT / "cache"
DEADLINES = {"registration_deadline", "submission_deadline"}



# A deadline whose label says it is for entrants already through a round, not for new entrants.
LATER_ROUND = re.compile(r"決賽|複賽|複審|入圍|晉級|決選|補件")
TODAY = os.environ.get("BUILD_DATE") or datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def entry_deadline(rec, today: str = TODAY):
    """The deadline a new entrant must meet, as (date, time or ""); None when the documents give none.

    Registration deadlines count; without any, submission deadlines do. Deadlines for entrants
    already through a round (LATER_ROUND) do not count. Of the rest, the first on or after `today`
    (a contest in stages or batches is open while one stage is), else the last one: then the
    contest is closed. Pages, archive, re-check and the comparison of two readings use this date."""
    def dated(kind):
        return sorted((d["date"], d["time"] or "") for d in rec["dates"]
                      if d["kind"] == kind and d["date"] and not LATER_ROUND.search(d["label"]))
    found = dated("registration_deadline") or dated("submission_deadline")
    if not found:
        return None
    return next((d for d in found if d[0] >= today), found[-1])

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


class Cache:
    def __init__(self):
        path = CACHE / "index.json"
        self.index = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.texts = {}

    def text(self, url):
        if url not in self.index:
            return None
        if url not in self.texts:
            path = CACHE / f"{self.index[url]['sha256']}.txt"
            self.texts[url] = normalize(path.read_text(encoding="utf-8")) if path.exists() else None
        return self.texts[url]


def date_in_quote(iso: str, quote: str) -> str:
    """'ok', 'no-year' or 'missing': do the month and day (and year) of iso appear in quote?"""
    y, m, d = (int(x) for x in iso.split("-"))
    q = re.sub(r"\s+", " ", quote)
    md = re.search(rf"(?<!\d)0?{m}\s*[/\-.月]\s*0?{d}(?!\d)", q)
    if not md:
        return "missing"
    if re.search(rf"(?<!\d)({y}|{y - 1911})(?!\d)", q):
        return "ok"
    return "no-year"


# Personal contact details must not be copied into a record, not even inside a quote.
CONTACT = [
    ("e-mail address", re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")),
    ("phone number", re.compile(r"(?<!\d)(\(?0\d{1,2}\)?[-\s]?\d{3,4}[-\s]?\d{3,4}|09\d{2}[-\s]?\d{3}[-\s]?\d{3})(?!\d)")),
]


def contact_details(rec) -> list:
    text = json.dumps({k: v for k, v in rec.items() if k not in ("links", "found_via")}, ensure_ascii=False)
    text = re.sub(r'"url": "[^"]*"', "", text)
    return [name for name, pattern in CONTACT if pattern.search(text)]


def check_fact(name, fact, unknown, cache, errors, warnings):
    """Return True when the fact is supported: a checked quote, or documents read that say nothing."""
    basis, evidence = fact["basis"], fact["evidence"]
    if basis == "unread":
        if not unknown:
            errors.append(f"{name}: basis is 'unread' but a value is given")
        return False
    if not evidence:
        errors.append(f"{name}: basis '{basis}' needs at least one evidence entry")
        return False
    ok = True
    quotes = 0
    for ev in evidence:
        text = cache.text(ev["url"])
        if text is None:
            errors.append(f"{name}: evidence document is not in the cache: {ev['url']}")
            ok = False
            continue
        if "quote" in ev:
            quotes += 1
            if normalize(ev["quote"]) not in text:
                errors.append(f"{name}: quote not found in the document: {ev['quote'][:40]}")
                ok = False
    if basis == "quote" and quotes == 0:
        errors.append(f"{name}: basis 'quote' but no evidence carries a quote")
        ok = False
    return ok


def check(path: Path, cache: Cache):
    errors, warnings = [], []
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"not valid JSON: {e}"], [], "unverified"
    schema_errors = sorted(Draft202012Validator(SCHEMA).iter_errors(rec), key=lambda e: list(e.path))
    if schema_errors:
        return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message[:160]}" for e in schema_errors], [], "unverified"

    for name in contact_details(rec):
        errors.append(f"personal contact detail in the record ({name}): leave it out, even inside a quote")

    if rec["id"] != path.stem:
        errors.append(f"id '{rec['id']}' does not match the file name")

    supported = {}
    el = rec["eligibility"]
    supported["eligibility"] = check_fact("eligibility", el, not el["levels"], cache, errors, warnings)
    for key, unknown in (("attendance", rec["attendance"]["value"] == "unknown"),
                         ("fee", rec["fee"]["value"] == "unknown"),
                         ("ai_policy", rec["ai_policy"]["value"] == "unknown"),
                         ("prizes", rec["prizes"]["text"] is None)):
        supported[key] = check_fact(key, rec[key], unknown, cache, errors, warnings)

    deadline_ok = False
    for i, d in enumerate(rec["dates"]):
        name = f"dates[{i}] {d['label']}"
        ok = check_fact(name, d, d["date"] is None, cache, errors, warnings)
        if d["date"]:
            try:
                date.fromisoformat(d["date"])
            except ValueError:
                errors.append(f"{name}: {d['date']} is not a real date")
                continue
            if d["basis"] == "absent":
                errors.append(f"{name}: a date cannot rest on basis 'absent'")
                ok = False
            if ok:
                found = [date_in_quote(d["date"], ev["quote"]) for ev in d["evidence"] if "quote" in ev]
                if "ok" in found:
                    pass
                elif "no-year" in found:
                    warnings.append(f"{name}: the quote gives month and day but no year")
                else:
                    errors.append(f"{name}: {d['date']} does not appear in its quote")
                    ok = False
        if ok and d["kind"] in DEADLINES and d["date"]:
            deadline_ok = True
    supported["deadline"] = deadline_ok

    urls = [rec["links"]["official"], rec["links"]["registration"]]
    urls += [l["url"] for l in rec["links"]["rules"]] + [f["url"] for f in rec["found_via"]]
    if not any(urls):
        errors.append("no link at all: a reader could not find the contest")

    v = rec["verification"]
    key_ok = all(supported[k] for k in KEY_FACTS)
    if v["method"] in ("migrated", "disputed") or not v["last_verified"] or not key_ok:
        level = "unverified"
        missing = [k for k in KEY_FACTS if not supported[k]]
        if missing:
            warnings.append("no checked support for: " + ", ".join(missing))
    else:
        level = "verified" if v["method"] == "dual" else "checked"
    return errors, warnings, level


def main():
    cache = Cache()
    failed = 0
    levels = {}
    for path in sorted((ROOT / "data/contests").glob("*.json")):
        errors, warnings, level = check(path, cache)
        levels[level] = levels.get(level, 0) + 1
        print(f"{'ERROR' if errors else 'ok':5} {level:10} {path.name}")
        for e in errors:
            print(f"      error: {e}")
        for w in warnings:
            print(f"      note:  {w}")
        failed += bool(errors)
    print(f"\n{sum(levels.values())} records, {failed} with errors; " + ", ".join(f"{k} {n}" for k, n in sorted(levels.items())))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
