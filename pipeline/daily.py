"""The daily run: queue, re-check, read, build.

Run: uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/daily.py [--limit N] [--jobs N]

1. Add the contests of the newest daily-report snapshot to data/candidates.json.
2. Re-check every open record: fetch its documents again. When the text is unchanged and the
   checks still pass, the documents have been read again today: last_verified becomes today.
   When a document changed, the contest is queued to be read again under the same id.
3. Read queued candidates with the first reader (pipeline/extract.py), at most --limit; then give
   at most --second open single-reader records to the second reader, soonest deadline first.
   The second reader's quota (Codex) runs out after about 45 long readings, so it confirms the
   key facts of the contests that matter most instead of reading everything.
4. A record that still fails the checks is moved to data/stale/ so that it is not published.
5. Write the pages and data files (pipeline/build_pages.py).
6. Write a summary to data/runs/<date>.json.

Nothing here commits or publishes; the deploy workflow does that from the repository.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
import extract  # noqa: E402
from fetch import cached_text, fact_changes, fingerprint_of, load_index  # noqa: E402
from validate import ROOT, Cache, check, entry_deadline  # noqa: E402

TODAY = cq.TODAY
CONTESTS = ROOT / "data/contests"


def open_records():
    """Records a new entrant can still join (or whose deadline is not known yet)."""
    for path in sorted(CONTESTS.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        due = entry_deadline(rec)
        if due is None or due[0] >= TODAY:
            yield path, rec


def evidence_urls(rec):
    urls = {ev["url"] for fact in (rec["eligibility"], *rec["dates"], rec["attendance"], rec["fee"], rec["prizes"], rec["ai_policy"])
            for ev in fact["evidence"]}
    return sorted(urls)


def recheck():
    """Returns {'confirmed': [...], 'changed': [...], 'unreachable': [...]}."""
    result = {"confirmed": [], "changed": [], "unreachable": []}
    queue = cq.load()
    for path, rec in open_records():
        if rec["verification"]["last_verified"] == TODAY:
            continue
        changed, failed = [], []
        for url in evidence_urls(rec):
            # A view counter that moved, or a new headline in a sidebar, is not a changed document:
            # only added or removed lines about deadlines, dates or registration call for reading again.
            # A fact whose quote was edited away also fails the check below and is read again.
            entry_before = load_index().get(url)
            _, err = extract.get(url)
            entry_after = load_index().get(url)
            if err:
                failed.append(url)
            elif fingerprint_of(entry_before) != fingerprint_of(entry_after) and \
                    fact_changes(cached_text(entry_before), cached_text(entry_after)):
                changed.append(url)
        if failed:
            result["unreachable"].append(rec["id"])
            continue
        errors, _, _ = check(path, Cache())
        if not changed and not errors:
            rec["verification"]["last_verified"] = TODAY
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result["confirmed"].append(rec["id"])
            continue
        result["changed"].append(rec["id"])
        urls = [{"url": u, "role": "rules", "name": ""} for u in cq.record_urls(rec) - {f["url"] for f in rec["found_via"]}]
        urls += [{"url": f["url"], "role": "announcement", "name": f["name"]} for f in rec["found_via"] if f["url"]]
        cand = next((c for c in queue if c.get("record") == rec["id"]), None)
        if not cand:
            cand = {"key": f"c{len(queue) + 1:04d}", "title": rec["title"], "deadline": None, "urls": urls,
                    "seen_in": "recheck", "first_seen": rec["first_seen"], "last_seen": TODAY, "attempts": 0}
            queue.append(cand)
        cand.update(status="new", record=rec["id"], attempts=0,
                    note="文件有變動，重新讀取" if changed else "原句已不在文件裡，重新讀取")
    cq.save(queue)
    return result


def set_aside_failing():
    stale = []
    for path in sorted(CONTESTS.glob("*.json")):
        errors, _, _ = check(path, Cache())
        if errors:
            target = ROOT / "data/stale" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, target)
            stale.append({"id": path.stem, "error": errors[0]})
    return stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--second", type=int, default=15, help="second readings per run")
    ap.add_argument("--no-read", action="store_true", help="queue and re-check only")
    args = ap.parse_args()

    sys.argv = [sys.argv[0]]
    cq.main()
    checked = recheck()
    print(f"re-check: {len(checked['confirmed'])} confirmed, {len(checked['changed'])} changed, "
          f"{len(checked['unreachable'])} unreachable", flush=True)

    outcomes = []
    if not args.no_read:
        queue = cq.load()
        todo = [c for c in queue if c["status"] == "new" or (c["status"] == "failed" and c.get("attempts", 0) < cq.MAX_ATTEMPTS)]
        todo.sort(key=lambda c: (c.get("record") is None, c["status"] != "new", c.get("deadline") or "9999"))
        todo = todo[: args.limit]
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            outcomes = list(pool.map(lambda c: extract.safe_process(c, extract.READERS[:1]), todo))

        seconds = extract.second_readings(extract.READERS, args.second, args.jobs)
    else:
        seconds = []

    stale = set_aside_failing()
    import subprocess  # noqa: PLC0415

    build = subprocess.run([sys.executable, "-I", str(ROOT / "pipeline/build_pages.py")], capture_output=True, text=True)
    print(build.stdout.strip(), build.stderr.strip(), sep="\n")

    queue = cq.load()
    status = {}
    for c in queue:
        status[c["status"]] = status.get(c["status"], 0) + 1
    summary = {
        "date": TODAY,
        "recheck": checked,
        "read": [{"status": o["status"], "record": o["record"], "note": o["note"]} for o in outcomes],
        "second_readings": [{"record": r, "outcome": o} for r, o in seconds],
        "set_aside": stale,
        "queue": status,
        "records": len(list(CONTESTS.glob("*.json"))),
    }
    runs = ROOT / "data/runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{TODAY}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("queue", "records")}, ensure_ascii=False))
    sys.exit(build.returncode)


if __name__ == "__main__":
    main()
