"""The daily run, in rounds: the script prepares tasks, agents do them, the script finishes them.

Run: uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/daily.py <step> [options]
  prepare [--limit N] [--second N] [--triage N] [--no-discover] [--no-recheck] [--force]
  finish
RUN.md says how an agent runs the whole update with these two steps.

prepare
1. Once a day: read the sources' list pages (pipeline/discover.py), then re-check every watched
   record (open, or closed within 14 days) with the comparison of pipeline/upstream.py: fetch each
   document once and compare it with the baseline in upstream/manifest.json. No difference, every
   document read and the checks pass: last_verified becomes today and the baseline is renewed. A
   difference (a quote gone, lines about dates, registration or fees added or removed, a correction
   posted, a document gone): the contest is queued to be read again under the same id, even when
   another of its documents could not be read. The same unresolved change does not queue it again
   once its readings failed.
2. Settle by link the announcements that are already a candidate or a record; write at most
   --triage triage tasks for the rest (pipeline/triage.py).
3. Write first-reading tasks for at most --limit queued candidates, and second-reading tasks for at
   most --second open records read once, soonest deadline first (pipeline/extract.py).
4. List the tasks, with the prompt for each, in work/TODO.md (and work/todo.json for finish).

finish
1. Apply every task that has an out.json: triage results become candidates, readings become
   records. A task without out.json changes nothing and comes back in a later round.
2. A record that fails the checks is moved to data/stale/ so that it is not published.
3. Write the pages and data files (pipeline/build_pages.py).
4. Add the round to data/runs/<date>.json and say whether another round has work.

Nothing here commits or publishes; scripts/publish-daily.sh does that.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
import discover  # noqa: E402
import extract  # noqa: E402
import triage  # noqa: E402
import upstream as up  # noqa: E402
from fetch import store  # noqa: E402
from validate import ROOT, Cache, check  # noqa: E402

TODAY = cq.TODAY
CONTESTS = ROOT / "data/contests"
WORK = ROOT / "work"
TODO_JSON = WORK / "todo.json"
TODO_MD = WORK / "TODO.md"
RUN_FILE = ROOT / "data/runs" / f"{TODAY}.json"
PROMPT = ("Work in the folder {folder}. Read brief.md and task.md there and follow brief.md exactly. "
          "Write out.json there and run `python3 check.py` in that folder until it prints OK.")


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
            cand = {"key": cq.next_key(queue), "title": rec["title"], "deadline": None, "urls": urls,
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


def load_run():
    return json.loads(RUN_FILE.read_text(encoding="utf-8")) if RUN_FILE.exists() else {"date": TODAY}


def save_run(run):
    RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_FILE.write_text(json.dumps(run, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def prepare(args):
    if TODO_JSON.exists() and not args.force:
        sys.exit("tasks from an earlier prepare are waiting: run `pnpm daily finish` first (or prepare --force)")
    shutil.rmtree(extract.TASKS, ignore_errors=True)
    run = load_run()
    if "discover" not in run and not args.no_discover:
        sys.argv = [sys.argv[0]]
        discover.main()
        run = load_run()
    if "recheck" not in run and not args.no_recheck:
        checked = recheck()
        print(f"re-check: {len(checked['confirmed'])} confirmed, {len(checked['changed'])} changed, "
              f"{len(checked['unreachable'])} unreachable", flush=True)
        run = load_run()
        run["recheck"] = checked
        save_run(run)

    queue = cq.load()
    discovered = triage.load_discovered()
    cq.expire(queue)
    cq.link_records(queue)
    settled = triage.match_known(discovered, queue)
    tasks = []
    for name in triage.write_tasks(discovered, queue, args.triage):
        tasks.append({"folder": rel(extract.TASKS / name), "kind": "triage", "what": "sort announcements"})
    for cand in extract.first_todo(queue, args.limit):
        folder = extract.TASKS / f"{cand['key']}-1"
        problem = extract.write_task(folder, cand, 1, cand.get("record"))
        if problem:
            cand["attempts"] = cand.get("attempts", 0) + 1
            cand.update(status="given_up" if cand["attempts"] >= cq.MAX_ATTEMPTS else "failed", note=problem)
            print(f"[{cand['key']}] {cand['status']}: {problem}", flush=True)
            continue
        tasks.append({"folder": rel(folder), "kind": "read", "reading": 1, "key": cand["key"], "what": cand["title"]})
    for cand, rid in extract.second_todo(queue, args.second):
        folder = extract.TASKS / f"{cand['key']}-2"
        problem = extract.write_task(folder, cand, 2, rid)
        if problem:
            second = cand.setdefault("second", {"attempts": 0})
            second["attempts"] += 1
            second["note"] = problem
            print(f"[{cand['key']}] no second reading: {problem}", flush=True)
            continue
        tasks.append({"folder": rel(folder), "kind": "read", "reading": 2, "key": cand["key"], "record": rid,
                      "what": cand["title"]})
    cq.save(queue)
    triage.save_discovered(discovered)
    if settled:
        print(f"{settled} announcements matched a candidate or a record by link")
    WORK.mkdir(exist_ok=True)
    TODO_JSON.write_text(json.dumps({"date": TODAY, "tasks": tasks}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not tasks:  # the re-check may still have changed records: write the pages now
        print("no tasks: nothing to read")
        finish(args)
        return
    labels = {"triage": "sort announcements", 1: "first reading", 2: "second reading"}
    lines = [
        f"# Tasks of {TODAY}", "",
        "Give each task to an agent in a fresh context: a new subagent or session that has seen neither this",
        "conversation, nor another task, nor the catalogue's records. Give it this prompt, with the folder filled in:", "",
        "> " + PROMPT.format(folder="<folder>"), "",
        "Tasks may run at the same time. Never give two tasks to one context. When every task has ended,",
        "done or not, run `pnpm daily finish`.", "",
    ]
    for t in tasks:
        label = labels[t.get("reading", t["kind"])]
        lines.append(f"- `{t['folder']}`: {label}" + (f", {t['what'][:50]}" if t["kind"] == "read" else ""))
    TODO_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    counts = {}
    for t in tasks:
        label = labels[t.get("reading", t["kind"])]
        counts[label] = counts.get(label, 0) + 1
    print(f"{len(tasks)} tasks ({', '.join(f'{k} {v}' for k, v in counts.items())}): see {rel(TODO_MD)}")


def finish(_args):
    if not TODO_JSON.exists():
        sys.exit("nothing to finish: run `pnpm daily prepare` first")
    todo = json.loads(TODO_JSON.read_text(encoding="utf-8"))
    queue = cq.load()
    discovered = triage.load_discovered()
    by_key = {c["key"]: c for c in queue}
    results = []
    for t in todo["tasks"]:
        folder = ROOT / t["folder"]
        try:
            if t["kind"] == "triage":
                line = triage.finish(folder, discovered, queue)
            elif t["reading"] == 1:
                line = extract.finish_first(by_key[t["key"]], folder)
            else:
                line = extract.finish_second(by_key[t["key"]], folder)
        except Exception as e:  # noqa: BLE001  one task must not stop the others
            line = f"error: {type(e).__name__}: {str(e)[:200]}"
            if t["kind"] == "read" and t["reading"] == 1:
                cand = by_key[t["key"]]
                cand["attempts"] = cand.get("attempts", 0) + 1
                cand.update(status="failed", note=line)
        print(f"[{folder.name}] {line}", flush=True)
        results.append({"task": folder.name, "result": line})
    cq.save(queue)
    triage.save_discovered(discovered)

    stale = set_aside_failing()
    build = subprocess.run([sys.executable, "-I", str(ROOT / "pipeline/build_pages.py")], capture_output=True, text=True)
    print(build.stdout.strip(), build.stderr.strip(), sep="\n")
    TODO_JSON.unlink()  # only now: publish-daily refuses while it exists, so pages never lag the records

    status = {}
    for c in queue:
        status[c["status"]] = status.get(c["status"], 0) + 1
    run = load_run()
    run.setdefault("rounds", []).append({"tasks": results, "set_aside": stale})
    run["queue"] = status
    run["announcements_waiting"] = sum(1 for e in discovered.values() if e["outcome"] == "new")
    run["records"] = len(list(CONTESTS.glob("*.json")))
    save_run(run)
    waiting = (run["announcements_waiting"] + len(extract.first_todo(queue, 10 ** 6))
               + len(extract.second_todo([dict(c) for c in queue], 10 ** 6)))
    print(json.dumps({k: run[k] for k in ("queue", "announcements_waiting", "records")}, ensure_ascii=False))
    print(f"work left for another round: {waiting} items" if waiting else "no work left")
    sys.exit(build.returncode)


def main():
    ap = argparse.ArgumentParser()
    steps = ap.add_subparsers(dest="step", required=True)
    p = steps.add_parser("prepare", help="write the tasks of a round")
    p.add_argument("--limit", type=int, default=30, help="first readings")
    p.add_argument("--second", type=int, default=30, help="second readings")
    p.add_argument("--triage", type=int, default=4, help="triage tasks (each up to 150 announcements)")
    p.add_argument("--no-discover", action="store_true", help="do not read the sources' list pages")
    p.add_argument("--no-recheck", action="store_true", help="do not re-check the watched records")
    p.add_argument("--force", action="store_true", help="drop tasks prepared earlier and not finished")
    steps.add_parser("finish", help="apply the tasks that were done, then write the pages")
    args = ap.parse_args()
    prepare(args) if args.step == "prepare" else finish(args)


if __name__ == "__main__":
    main()
