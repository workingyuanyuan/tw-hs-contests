"""The daily run: queue, re-check, read, build.

Run: uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/daily.py [--limit N] [--jobs N]

1. Add the contests of the newest daily-report snapshot to data/candidates.json.
2. Re-check every watched record (open, or closed within 14 days) with the comparison of
   pipeline/upstream.py: fetch each document once and compare it with the baseline in
   upstream/manifest.json. No difference, every document read and the checks pass: the documents
   have been read again today, last_verified becomes today and the baseline is renewed. A
   difference (a quote gone, lines about dates, registration or fees added or removed, a
   correction posted, a document gone): the contest is queued to be read again under the same id,
   even when another of its documents could not be read. The same unresolved change does not
   queue it again once its readings failed.
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
import upstream as up  # noqa: E402
from fetch import store  # noqa: E402
from validate import ROOT, Cache, check  # noqa: E402

TODAY = cq.TODAY
CONTESTS = ROOT / "data/contests"


REASONS = {"quote gone": "原句已不在文件裡，重新讀取", "source changed": "文件有變動，重新讀取",
           "correction posted": "主辦單位貼出更正，重新讀取", "document gone": "文件已移除，重新讀取",
           "checks": "原句已不在文件裡，重新讀取"}


def recheck():
    """Returns {'confirmed': [...], 'changed': [...], 'unreachable': [...]}."""
    result = {"confirmed": [], "changed": [], "unreachable": []}
    records = list(up.watched())
    seen = up.observe(sorted({u for _, rec in records for u in up.sources(rec)}))
    results = up.compare_all(records, seen, up.load_manifest())
    unread = {u for r in results.values() for u in r["unread"]}
    # The cache holds what was read today, so that readers and the checks see the same text.
    for url, got in seen.items():
        if "error" not in got and url not in unread:
            store(url, got["body"], got["text"], got["links"], got["info"])
    queue = cq.load()
    renewed = {}
    for path, rec in records:
        r = results[rec["id"]]
        diffs = [(kind, detail) for kind, detail in r["diffs"] if kind not in up.REPORT_ONLY]
        if not diffs and r["unread"]:
            result["unreachable"].append(rec["id"])
            continue
        if not diffs:
            errors, _, _ = check(path, Cache())
            if not errors:
                rec["verification"]["last_verified"] = TODAY
                path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                renewed[rec["id"]] = up.baseline_from_seen(rec, seen)
                result["confirmed"].append(rec["id"])
                continue
            diffs = [("checks", errors[0])]
        result["changed"].append(rec["id"])
        change = r["change"] or up.short("checks " + diffs[0][1])
        cand = next((c for c in queue if c.get("record") == rec["id"]), None)
        if cand and cand.get("change") == change and cand["status"] in ("failed", "given_up", "new"):
            continue  # the same change, already queued or given up after failed readings
        # every document of the record, and the links that announce the change, so that the readers see them
        docs = (cq.record_urls(rec) | set(up.sources(rec))) - {f["url"] for f in rec["found_via"]}
        urls = [{"url": u, "role": "rules", "name": ""} for u in [*r["targets"], *sorted(docs - set(r["targets"]))]]
        urls += [{"url": f["url"], "role": "announcement", "name": f["name"]} for f in rec["found_via"] if f["url"]]
        if not cand:
            cand = {"key": f"c{len(queue) + 1:04d}", "title": rec["title"], "deadline": None, "urls": urls,
                    "seen_in": "recheck", "first_seen": rec["first_seen"], "last_seen": TODAY, "attempts": 0}
            queue.append(cand)
        cand.update(status="new", record=rec["id"], attempts=0, change=change, urls=urls, note=REASONS[diffs[0][0]])
    cq.save(queue)
    up.save_baselines(renewed, keep={rec["id"] for _, rec in records})
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
