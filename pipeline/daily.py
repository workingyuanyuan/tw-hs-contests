"""The daily run, in rounds: the script prepares tasks, agents do them, the script finishes them.

Run: uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/daily.py <step> [options]
  prepare [--limit N] [--second N] [--triage N] [--search N] [--no-discover] [--no-recheck] [--force]
  finish
  reread <id or candidate key> [...]
  same <fuller id> <other id> [<other id> ...]
  distinct <id> <id>
RUN.md says how an agent runs the whole update with these steps.

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
3. Give what was given up a week ago another try while it may be open; write first-reading tasks
   for at most --limit queued candidates, second-reading tasks for at most --second open records
   read once, soonest deadline first (pipeline/extract.py), and search tasks for at most --search
   candidates whose rules were not found (pipeline/search.py).
4. List the tasks, with the prompt for each, in work/TODO.md (and work/todo.json for finish).

finish
1. Apply every task that has an out.json: triage results become candidates, readings become
   records, links that a search found and the script kept join their candidates. A task without out.json changes nothing and comes back in a later round.
2. Records of one contest (the same edition, title and an organizer, under two ids) become one:
   the id seen first stays, with the best-verified reading, and the candidates of the others follow
   it (pipeline/extract.py merge_duplicates). Pairs judged the same contest (same, below) become one
   as well. Pairs that may be one contest and that no judgement settles are listed as
   `[duplicate?]` lines (extract.possible_duplicates), for the agent running the update to judge.
   A record that fails the checks is moved to data/stale/ so that it is not published (for
   example when a document it quotes was removed: its server answered 404 or 410).
3. Write the pages and data files (pipeline/build_pages.py).
4. Add the round to data/runs/<date>.json and say whether another round has work.

reread
Queue records to be read again under their ids, from all their documents: for wording a reader
wrote (the summary, a deliverable, the prizes) that the prose review flagged. The next prepare
gives each a first reading before any other; the new reading replaces the record, and its second
reading starts over. A record already queued is left as it is.
A candidate key (c0303) queues a candidate that was skipped as not a contest, once the rules of
what the catalogue includes have changed: it gets a first reading again.

same, distinct
Record a judgement on a `[duplicate?]` pair in data/same-contests.json. same: the records are one
contest edition (venues of one contest included); the first id names the fuller reading, whose content
the merged record keeps under the id seen first; the merge runs at once and the pages are written
again. distinct: two contests, or two tracks, divisions or stages of one with their own entry, or two
editions; the pair is not listed again.

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
import search  # noqa: E402
import triage  # noqa: E402
import upstream as up  # noqa: E402
from fetch import mark_gone, store  # noqa: E402
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
        elif "error" in got:  # a removed document fails the checks of the records that quote it
            mark_gone(url, got["error"])
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
        if cand and cand.get("change") == change and cand["status"] in ("failed", "given_up", "new", "search"):
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


def set_aside_failing(queue):
    """Move the records that fail the checks to data/stale/ and queue each to be read again under its
    id, from all its links, unless it is queued already."""
    stale = []
    for path in sorted(CONTESTS.glob("*.json")):
        errors, _, _ = check(path, Cache())
        if not errors:
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        target = ROOT / "data/stale" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, target)
        stale.append({"id": path.stem, "error": errors[0]})
        cand = next((c for c in queue if c.get("record") == rec["id"]), None)
        if cand and cand["status"] in ("new", "failed", "search", "given_up"):
            continue
        docs = (cq.record_urls(rec) | set(up.sources(rec))) - {f["url"] for f in rec["found_via"]}
        urls = [{"url": u, "role": "rules", "name": ""} for u in sorted(docs)]
        urls += [{"url": f["url"], "role": "announcement", "name": f["name"]} for f in rec["found_via"] if f["url"]]
        if not cand:
            cand = {"key": cq.next_key(queue), "title": rec["title"], "deadline": None, "seen_in": "set aside",
                    "first_seen": rec["first_seen"], "last_seen": TODAY, "record": rec["id"]}
            queue.append(cand)
        cand.update(status="new", attempts=0, urls=urls, note="不符檢查而暫不刊登，重新讀取")
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
    revived = extract.retry(queue)
    if revived:
        print(f"{revived} given up a week ago or more: tried again", flush=True)
    settled = triage.match_known(discovered, queue)
    tasks = []
    for name in triage.write_tasks(discovered, queue, args.triage):
        tasks.append({"folder": rel(extract.TASKS / name), "kind": "triage", "what": "sort announcements"})
    for cand in extract.first_todo(queue, args.limit):
        folder = extract.TASKS / f"{cand['key']}-1"
        problem = extract.write_task(folder, cand, 1, cand.get("record"))
        if problem:
            cand["attempts"] = cand.get("attempts", 0) + 1
            cand.update(tried=TODAY, note=problem)
            if cand.get("searched"):
                cand["status"] = "given_up" if cand["attempts"] >= cq.MAX_ATTEMPTS else "failed"
            else:  # its own links are unreachable: look for the organizer's page
                cand.update(status="search", after_search="given_up")
            print(f"[{cand['key']}] {cand['status']}: {problem}", flush=True)
            continue
        tasks.append({"folder": rel(folder), "kind": "read", "reading": 1, "key": cand["key"], "what": cand["title"]})
    for cand, rid in extract.second_todo(queue, args.second):
        folder = extract.TASKS / f"{cand['key']}-2"
        problem = extract.write_task(folder, cand, 2, rid)
        if problem:
            second = cand.setdefault("second", {"attempts": 0})
            second["attempts"] += 1
            second.update(note=problem, tried=TODAY)
            print(f"[{cand['key']}] no second reading: {problem}", flush=True)
            continue
        tasks.append({"folder": rel(folder), "kind": "read", "reading": 2, "key": cand["key"], "record": rid,
                      "what": cand["title"]})
    for cand in [c for c in queue if c["status"] == "search"][:args.search]:
        folder = extract.TASKS / f"{cand['key']}-s"
        search.write_task(folder, cand)
        tasks.append({"folder": rel(folder), "kind": "search", "key": cand["key"], "what": cand["title"]})
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
    labels = {"triage": "sort announcements", 1: "first reading", 2: "second reading", "search": "search"}
    lines = [
        f"# Tasks of {TODAY}", "",
        "Give each task to an agent in a fresh context: a new subagent or session that has seen neither this",
        "conversation, nor another task, nor the catalogue's records. Give it this prompt, with the folder filled in:", "",
        "> " + PROMPT.format(folder="<folder>"), "",
        "Tasks may run at the same time. Never give two tasks to one context. A search task needs an agent",
        "with a web search tool; without one, leave it. When every task has ended, done or not, run",
        "`pnpm daily finish`.", "",
    ]
    for t in tasks:
        label = labels[t.get("reading", t["kind"])]
        lines.append(f"- `{t['folder']}`: {label}" + (f", {t['what'][:50]}" if t["kind"] != "triage" else ""))
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
        cand = by_key.get(t.get("key"))
        counted = (cand or {}).get("attempts"), ((cand or {}).get("second") or {}).get("attempts")
        try:
            if t["kind"] == "triage":
                line = triage.finish(folder, discovered, queue)
            elif t["kind"] == "search":
                line = search.finish(folder, by_key[t["key"]])
            elif t["reading"] == 1:
                line = extract.finish_first(by_key[t["key"]], folder)
            else:
                line = extract.finish_second(by_key[t["key"]], folder)
        except Exception as e:  # noqa: BLE001  one task must not stop the others
            line = f"error: {type(e).__name__}: {str(e)[:200]}"
            if t["kind"] == "read" and t["reading"] == 1:
                cand.pop("need", None)
                if cand.get("attempts") == counted[0]:  # not counted before the error
                    cand.update(attempts=(cand.get("attempts") or 0) + 1, tried=TODAY)
                line = extract.fail_first(cand, line)
            elif t["kind"] == "read":
                second = cand.setdefault("second", {"attempts": 0})
                second.pop("need", None)
                if second["attempts"] == (counted[1] or 0):
                    second.update(attempts=second["attempts"] + 1, tried=TODAY)
                second["note"] = line[:200]
        print(f"[{folder.name}] {line}", flush=True)
        results.append({"task": folder.name, "result": line})
    try:
        merged = extract.merge_duplicates(queue)
    except Exception as e:  # noqa: BLE001  a record that cannot be compared must not stop the round
        merged = [f"error: {type(e).__name__}: {str(e)[:200]}"]
    for line in merged:
        print(f"[merge] {line}", flush=True)
    possible = extract.possible_duplicates()
    for line in possible:
        print(f"[duplicate?] {line}", flush=True)
    stale = set_aside_failing(queue)
    cq.save(queue)
    triage.save_discovered(discovered)

    build = subprocess.run([sys.executable, "-I", str(ROOT / "pipeline/build_pages.py")], capture_output=True, text=True)
    print(build.stdout.strip(), build.stderr.strip(), sep="\n")
    TODO_JSON.unlink()  # only now: publish-daily refuses while it exists, so pages never lag the records

    status = {}
    for c in queue:
        status[c["status"]] = status.get(c["status"], 0) + 1
    run = load_run()
    run.setdefault("rounds", []).append({"tasks": results, "merged": merged, "set_aside": stale})
    run["possible_duplicates"] = possible
    run["queue"] = status
    run["announcements_waiting"] = sum(1 for e in discovered.values() if e["outcome"] == "new")
    run["records"] = len(list(CONTESTS.glob("*.json")))
    save_run(run)
    waiting = (run["announcements_waiting"] + len(extract.first_todo(queue, 10 ** 6))
               + sum(c["status"] == "search" for c in queue)
               + len(extract.second_todo([dict(c) for c in queue], 10 ** 6)))
    print(json.dumps({k: run[k] for k in ("queue", "announcements_waiting", "records")}, ensure_ascii=False))
    print(f"work left for another round: {waiting} items" if waiting else "no work left")
    sys.exit(build.returncode)


def reread(args):
    queue = cq.load()
    for rid in args.ids:
        skipped = next((c for c in queue if c["key"] == rid), None)
        if skipped:  # a candidate key
            if skipped["status"] != "skipped":
                print(f"{rid}: {skipped['status']}, not skipped; reread a record by its id")
                continue
            skipped.pop("need", None)
            skipped.update(status="new", attempts=0, note="重新讀取：收錄範圍已修訂")
            print(f"{rid}: queued")
            continue
        path = CONTESTS / f"{rid}.json"
        if not path.exists():
            print(f"{rid}: no such record in data/contests/")
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        # the last candidate of the record, the one its second reading uses (extract.second_todo)
        cand = next((c for c in reversed(queue) if c.get("record") == rid), None)
        if any(c.get("record") == rid and c["status"] in ("new", "failed", "search") for c in queue):
            print(f"{rid}: already queued")
            continue
        docs = (cq.record_urls(rec) | set(up.sources(rec))) - {f["url"] for f in rec["found_via"]}
        urls = [{"url": u, "role": "rules", "name": ""} for u in sorted(docs)]
        urls += [{"url": f["url"], "role": "announcement", "name": f["name"]} for f in rec["found_via"] if f["url"]]
        if not cand:
            cand = {"key": cq.next_key(queue), "title": rec["title"], "deadline": None, "urls": urls,
                    "seen_in": "reread", "first_seen": rec["first_seen"], "last_seen": TODAY, "attempts": 0}
            queue.append(cand)
        cand.pop("need", None)
        cand.pop("joined", None)  # it reads the record's own documents now
        cand.update(status="new", record=rid, attempts=0, urls=urls, note="重新讀取：用語未通過審讀")
        print(f"{rid}: queued ({cand['key']})")
    cq.save(queue)


def judge_pair(ids, kind) -> bool:
    missing = [rid for rid in ids if not (CONTESTS / f"{rid}.json").exists()]
    if missing or len(set(ids)) < len(ids) or len(ids) < 2:
        print("give two or more ids of records in data/contests/: " + ", ".join(missing or ids))
        return False
    if TODO_JSON.exists():
        print("a round is prepared and not finished; run pnpm daily finish first")
        return False
    judged = extract.load_judged()
    pairs = [[ids[0], other] for other in ids[1:]]
    for pair in pairs:
        for k in ("same", "distinct"):  # the newest judgement of a pair replaces an older one
            judged[k] = [p for p in judged[k] if frozenset(p) != frozenset(pair)]
        judged[kind].append(pair)
    extract.save_judged(judged)
    return True


def same(args):
    if not judge_pair(args.ids, "same"):
        sys.exit(1)
    queue = cq.load()
    for line in extract.merge_duplicates(queue):
        print(f"[merge] {line}", flush=True)
    cq.save(queue)
    build = subprocess.run([sys.executable, "-I", str(ROOT / "pipeline/build_pages.py")], capture_output=True, text=True)
    print(build.stdout.strip(), build.stderr.strip(), sep="\n")
    sys.exit(build.returncode)


def distinct(args):
    if not judge_pair(args.ids, "distinct"):
        sys.exit(1)
    print(f"{args.ids[0]} and {args.ids[1]}: judged distinct")


def main():
    ap = argparse.ArgumentParser()
    steps = ap.add_subparsers(dest="step", required=True)
    p = steps.add_parser("prepare", help="write the tasks of a round")
    p.add_argument("--limit", type=int, default=30, help="first readings")
    p.add_argument("--second", type=int, default=30, help="second readings")
    p.add_argument("--triage", type=int, default=4, help="triage tasks (each up to 150 announcements)")
    p.add_argument("--search", type=int, default=10, help="search tasks")
    p.add_argument("--no-discover", action="store_true", help="do not read the sources' list pages")
    p.add_argument("--no-recheck", action="store_true", help="do not re-check the watched records")
    p.add_argument("--force", action="store_true", help="drop tasks prepared earlier and not finished")
    steps.add_parser("finish", help="apply the tasks that were done, then write the pages")
    r = steps.add_parser("reread", help="queue records, or skipped candidates, to be read again")
    r.add_argument("ids", nargs="+", help="record ids (data/contests/<id>.json) or candidate keys (c0303)")
    sm = steps.add_parser("same", help="judge records one contest edition, and merge them")
    sm.add_argument("ids", nargs="+", help="the fuller reading's id, then the others")
    d = steps.add_parser("distinct", help="judge two records different contests, tracks or editions")
    d.add_argument("ids", nargs=2, help="two record ids")
    args = ap.parse_args()
    {"prepare": prepare, "finish": finish, "reread": reread, "same": same, "distinct": distinct}[args.step](args)


if __name__ == "__main__":
    main()
