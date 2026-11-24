"""Triage tasks: sort the announcements discovery found into contests and the rest, and group the
announcements that name one contest, so that each contest is queued once.

pipeline/daily.py calls this module; it has no command of its own.

`match_known` first settles by link what needs no model: an announcement whose address is already a
candidate's or a record's. `write_tasks` puts the rest, in batches of BATCH titles, into task folders
(work/tasks/triage-NN/) with pipeline/triage.md, the titles (announcements.json), the open contests
already known (known.json) and check.py. Announcements whose titles share most of their words are
put in one batch, so that one agent sees the copies of a contest that several schools posted. The
agent judges from the titles only and writes out.json. `finish` applies it:
  not a contest              -> outcome "not_contest" (note: the agent's reason)
  same as a known candidate  -> its link is added to that candidate; outcome "queued"
  same as a known record     -> outcome "duplicate" (note: the record)
  otherwise                  -> a new candidate, with the links of every announcement grouped with it
A batch that was not run or fails its check leaves its announcements "new" for the next run.
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
from extract import bigrams  # noqa: E402
from validate import ROOT, entry_deadline  # noqa: E402

TASKS = ROOT / "work/tasks"
PIPELINE = ROOT / "pipeline"
DISCOVERED = ROOT / "data/discovered.json"
SOURCES = ROOT / "data/sources.json"
TODAY = cq.TODAY
BATCH = 150
ALIKE = 0.6  # share of title bigrams that puts two announcements in one batch


def load_discovered():
    return json.loads(DISCOVERED.read_text(encoding="utf-8")) if DISCOVERED.exists() else {}


def save_discovered(discovered):
    tmp = DISCOVERED.with_suffix(".tmp")
    tmp.write_text(json.dumps(discovered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(DISCOVERED)


def records():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "data/contests").glob("*.json"))]


def match_known(discovered, queue) -> int:
    """Settle by link the new announcements that are already a candidate or a record. Returns how many."""
    by_url = {cq.same_url(u["url"]): c for c in queue for u in c["urls"]}
    # open records only: an organizer may reuse a closed edition's page for the next one, which
    # triage then tells apart by its title
    rec_urls = {cq.same_url(u): r["id"] for r in records() if open_record(r) for u in cq.record_urls(r)}
    settled = 0
    for key, e in discovered.items():
        if e["outcome"] != "new":
            continue
        if key in by_url:
            e["outcome"], e["note"] = "queued", by_url[key]["key"]
            settled += 1
        elif key in rec_urls:
            e["outcome"], e["note"] = "duplicate", rec_urls[key]
            settled += 1
    return settled


def open_record(rec) -> bool:
    due = entry_deadline(rec)
    return not due or due[0] >= TODAY


def known_contests(queue) -> list:
    """Open contests an announcement may repeat: candidates waiting to be read, and records still open."""
    known = [{"ref": c["key"], "title": c["title"]} for c in queue
             if c["status"] in ("new", "failed") and not c.get("record")]
    known += [{"ref": rec["id"], "title": rec["title"]} for rec in records() if open_record(rec)]
    return known


def batches(entries) -> list:
    """Entries in batches of at most BATCH, alike titles together, newest announcements first."""
    groups = []  # [(grams, [entry])]
    for e in sorted(entries, key=lambda e: e.get("date") or "", reverse=True):
        grams = bigrams(e["title"])
        for g in groups:
            if grams and len(grams & g[0]) >= ALIKE * min(len(grams), len(g[0])):
                g[1].append(e)
                break
        else:
            groups.append((grams, [e]))
    out, cur = [], []
    for _, members in groups:
        if cur and len(cur) + len(members) > BATCH:
            out.append(cur)
            cur = []
        cur += members
    return out + ([cur] if cur else [])


def write_tasks(discovered, queue, limit: int) -> list:
    """Write at most `limit` triage folders. Returns their names."""
    names = {s["id"]: s["name"] for s in json.loads(SOURCES.read_text(encoding="utf-8"))}
    entries = [e for e in discovered.values() if e["outcome"] == "new"]
    known = known_contests(queue)
    written = []
    for i, batch in enumerate(batches(entries)[:limit], 1):
        folder = TASKS / f"triage-{i:02d}"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        items = [{"n": n, "title": e["title"], "source": names.get(e["sources"][0], e["sources"][0]),
                  "date": e.get("date"), "url": e["url"]} for n, e in enumerate(batch, 1)]
        (folder / "announcements.json").write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (folder / "known.json").write_text(json.dumps(known, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        shutil.copy(PIPELINE / "triage.md", folder / "brief.md")
        shutil.copy(PIPELINE / "check_out.py", folder / "check.py")
        (folder / "task.md").write_text(f"# Task\n\nToday: {TODAY}\nAnnouncements: {len(items)} in announcements.json\n"
                                        f"Contests already known: {len(known)} in known.json\n", encoding="utf-8")
        task = {"kind": "triage", "urls": [e["url"] for e in batch], "refs": [k["ref"] for k in known]}
        (folder / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(folder.name)
    return written


def problems(out, task) -> list:
    """What is wrong with a triage out.json, as a list of messages (empty: it may be applied)."""
    if not isinstance(out, dict) or not isinstance(out.get("items"), list):
        return ['out.json must be {"items": [...]}']
    errs, verdicts = [], {}
    count = len(task["urls"])
    refs = set(task["refs"])
    for it in out["items"]:
        n = it.get("n") if isinstance(it, dict) else None
        if not isinstance(n, int) or not 1 <= n <= count:
            errs.append(f"item {it!r:.60}: n must be a number from announcements.json")
            continue
        if n in verdicts:
            errs.append(f"n {n}: listed twice")
        v = it.get("verdict")
        verdicts[n] = v
        if v not in ("contest", "not"):
            errs.append(f"n {n}: verdict must be \"contest\" or \"not\"")
        if v == "contest" and not (isinstance(it.get("name"), str) and it["name"].strip()):
            errs.append(f"n {n}: a contest needs its name")
        d = it.get("deadline")
        if d is not None and not (isinstance(d, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", d)):
            errs.append(f"n {n}: deadline must be YYYY-MM-DD or null")
    for it in out["items"]:
        if not isinstance(it, dict) or it.get("verdict") != "contest" or it.get("same_as") is None:
            continue
        s, n = it["same_as"], it.get("n")
        if not isinstance(s, (int, str)) or isinstance(s, bool):
            errs.append(f"n {n}: same_as must be null, an n or a ref")
        elif isinstance(s, int):
            if not (isinstance(n, int) and s < n and verdicts.get(s) == "contest"):
                errs.append(f"n {n}: same_as {s} must be an earlier announcement marked contest")
        elif s not in refs:
            errs.append(f"n {n}: same_as {s!r} is neither an earlier n nor a ref in known.json")
    missing = sorted(set(range(1, count + 1)) - set(verdicts))
    if missing:
        errs.append(f"announcements without a verdict: n {', '.join(map(str, missing[:20]))}")
    return errs


def finish(folder: Path, discovered, queue) -> str:
    """Apply one triage folder. Returns a line for the log."""
    task = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    out_path = folder / "out.json"
    if not out_path.exists():
        return "not run"
    try:
        out = json.loads(out_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return f"not applied: out.json is not valid JSON ({str(e)[:60]})"
    errs = problems(out, task)
    if errs:
        return f"not applied: {errs[0]}"
    names = {s["id"]: s["name"] for s in json.loads(SOURCES.read_text(encoding="utf-8"))}
    by_key = {c["key"]: c for c in queue}
    made = {}  # n -> the candidate it joined or made, or the id of the record it repeats
    counts = {"not": 0, "new": 0, "joined": 0, "duplicate": 0}
    for it in sorted(out["items"], key=lambda it: it["n"]):
        url = task["urls"][it["n"] - 1]
        e = discovered.get(cq.same_url(url))
        if not e or e["outcome"] != "new":
            continue
        if it["verdict"] == "not":
            e["outcome"], e["note"] = "not_contest", (str(it.get("why") or "")[:120] or None)
            counts["not"] += 1
            continue
        link = {"url": e["url"], "role": "announcement", "name": names.get(e["sources"][0], e["sources"][0])}
        s = it.get("same_as")
        target = made.get(s) if isinstance(s, int) else (by_key.get(s) or s) if s else None
        if isinstance(target, str):  # a record
            made[it["n"]] = target
            e["outcome"], e["note"] = "duplicate", target
            counts["duplicate"] += 1
            continue
        cand = target
        if cand:
            if cq.same_url(url) not in {cq.same_url(u["url"]) for u in cand["urls"]}:
                cand["urls"].append(link)
                if cand["status"] in ("failed", "given_up"):  # a link its readings never had
                    cand["status"] = "new"
            cand["last_seen"] = TODAY
            if it.get("deadline") and not cand.get("deadline"):
                cand["deadline"] = it["deadline"]
            counts["joined"] += 1
        else:
            cand = {"key": cq.next_key(queue), "title": it["name"].strip(), "deadline": it.get("deadline"),
                    "urls": [link], "seen_in": "discover", "first_seen": TODAY, "last_seen": TODAY,
                    "status": "new", "attempts": 0, "record": None, "note": None}
            if cand["deadline"] and cand["deadline"] < TODAY:
                cand["status"] = "expired"
            queue.append(cand)
            by_key[cand["key"]] = cand
            counts["new"] += 1
        made[it["n"]] = cand
        e["outcome"], e["note"] = "queued", cand["key"]
    return (f"{counts['new']} new candidates, {counts['joined']} joined a candidate, "
            f"{counts['duplicate']} of a record, {counts['not']} not contests")
