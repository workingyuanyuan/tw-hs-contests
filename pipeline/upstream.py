"""Compare the documents of the watched contests with what their records were read from.

Run: pnpm upstream [--write]
     (uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/upstream.py)

Exit 0: no difference. 1: differences, one line each (`kind: <record id>: detail`; the page is
/contests/<id>/). 2: the comparison could not be made. It changes no record, page or cached text;
--write also records, in upstream/manifest.json, what was read for every contest without a
difference. upstream/README.md explains every line.

The daily run (pipeline/daily.py) uses the same comparison and acts on it, and pipeline/extract.py
records the baseline of a record when it writes one. What the baseline holds per document, keyed by
record id and URL: the fingerprint of its text, its length, short hashes of its lines about dates,
registration, fees or corrections, and short hashes of the links whose text announces a correction.
It keeps no source text.
"""
import argparse
import hashlib
import json
import re
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import FACT_WORDS, cached, fingerprint, meaningful_lines, read  # noqa: E402
from validate import ROOT, TODAY, entry_deadline, normalize  # noqa: E402

MANIFEST = ROOT / "upstream/manifest.json"
CONTESTS = ROOT / "data/contests"
GRACE_DAYS = 14  # a contest stays watched this long after its deadline: an extension can come after it
STALE_DAYS = 7  # a record whose documents could not be read for this long is reported
MAX_NOT_READ = 1 / 3  # more documents than this not read: the comparison was not made
COLLAPSE = 0.3  # a text shorter than this share of the baseline, with none of its quotes, was not read
# The text of a link that announces a change to the rules.
CORRECTION = re.compile(r"更正|修正|勘誤|延期|延長|展延|補充|異動|取消|停辦")
GONE = re.compile(r"\bHTTP (404|410)\b")
# Lines that the report shows but that do not count as differences in the daily run.
REPORT_ONLY = {"not in the manifest", "not read for a week"}

manifest_lock = threading.Lock()


def short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def watched(today: str = TODAY):
    """(path, record) of every contest open, or closed within GRACE_DAYS, or without a known deadline."""
    cutoff = (date.fromisoformat(today) - timedelta(days=GRACE_DAYS)).isoformat()
    for path in sorted(CONTESTS.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        due = entry_deadline(rec, today)
        if due is None or due[0] >= cutoff:
            yield path, rec


def facts(rec):
    yield "eligibility", rec["eligibility"]
    for d in rec["dates"]:
        yield d["label"] or d["kind"], d
    for name in ("attendance", "fee", "prizes", "ai_policy"):
        yield name, rec[name]


def sources(rec) -> list:
    """The documents a record rests on: those its evidence quotes or names, and its official page."""
    urls = {ev["url"] for _, fact in facts(rec) for ev in fact["evidence"]}
    if rec["links"]["official"]:
        urls.add(rec["links"]["official"])
    return sorted(urls)


def fact_lines(text: str) -> list:
    return [line for line in meaningful_lines(text) if FACT_WORDS.search(line)]


def baseline(text: str, links: list) -> dict:
    return {
        "fingerprint": fingerprint(text),
        "chars": len(text),
        "facts": sorted({short(line) for line in fact_lines(text)}),
        "corrections": sorted({short(link["url"]) for link in links if CORRECTION.search(link["text"])}),
    }


def observe(urls) -> dict:
    """Fetch each document once, without writing the cache: {url: {body, text, links, info} or {error}}."""
    seen = {}
    for url in urls:
        try:
            body, text, links, info = read(url)
            seen[url] = {"body": body, "text": text, "links": links, "info": info}
        except Exception as e:  # noqa: BLE001  one document must not stop the others
            seen[url] = {"error": f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:120]}"}
    return seen


def compare(rec, seen: dict, base: dict) -> dict:
    """{'diffs': [(kind, detail)], 'notes': [(kind, detail)], 'unread': [url], 'change': hash, 'targets': [url]}
    for one record. `change` identifies the whole change (every added or removed line, every new link),
    so that a second amendment is not taken for the first; `targets` are the links that announce it."""
    diffs, notes, unread, keys, targets = [], [], [], [], []
    for url in sources(rec):
        got, before = seen[url], base.get(url)
        quotes = [(name, ev["quote"]) for name, fact in facts(rec) for ev in fact["evidence"]
                  if ev["url"] == url and ev.get("quote")]
        if "error" in got:
            if GONE.search(got["error"]):
                diffs.append(("document gone", f"{url}: {got['error']}"))
                keys.append(f"gone {url}")
            else:
                unread.append(url)
                notes.append(("not read", f"{url}: {got['error']}"))
            continue
        text = normalize(got["text"])
        missing = [(name, q) for name, q in quotes if normalize(q) not in text]
        if before and before["chars"] and len(got["text"]) < COLLAPSE * before["chars"] \
                and len(missing) == len(quotes):
            # A sign-in page, a challenge or an error page served with status 200.
            unread.append(url)
            notes.append(("not read", f"{url}: the text fell from {before['chars']} to {len(got['text'])} characters"))
            continue
        for name, q in missing:
            diffs.append(("quote gone", f"{name}: 「{' '.join(q.split())[:30]}」 is no longer in {url}"))
            keys.append(f"quote {url} {short(q)}")
        if before is None:
            diffs.append(("not in the manifest", url))
            continue
        lines = fact_lines(got["text"])
        now = {short(line) for line in lines}
        added = list(dict.fromkeys(line for line in lines if short(line) not in before["facts"]))
        gone = sorted(set(before["facts"]) - now)
        removed = len(gone)
        if added or removed:
            keys.append(f"facts {url} +{' '.join(sorted(short(line) for line in added))} -{' '.join(gone)}")
            diffs.append(("source changed", f"{url}: {len(added)} lines about dates, registration or fees added, "
                          f"{removed} removed" + (f"; first added: 「{added[0][:50]}」" if added else "")))
        elif fingerprint(got["text"]) != before["fingerprint"]:
            notes.append(("text changed", url))
        posted = list({link["url"]: link for link in got["links"]
                       if CORRECTION.search(link["text"]) and short(link["url"]) not in before["corrections"]}.values())
        if posted:
            keys.append(f"links {url} " + " ".join(sorted(short(link["url"]) for link in posted)))
            targets += [link["url"] for link in posted]
            diffs.append(("correction posted", f"{url}: 「{posted[0]['text'][:40]}」 {posted[0]['url']}"))
    last = rec["verification"]["last_verified"]
    if unread and not diffs and last <= (date.fromisoformat(TODAY) - timedelta(days=STALE_DAYS)).isoformat():
        diffs.append(("not read for a week", f"last read on {last}; {len(unread)} of {len(sources(rec))} documents not read"))
    return {"diffs": diffs, "notes": notes, "unread": unread, "change": short("\n".join(sorted(keys))) if keys else None,
            "targets": list(dict.fromkeys(targets))}


def load_manifest() -> dict | None:
    if not MANIFEST.exists():
        return None
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = data.get("records") if isinstance(data, dict) else None
    def good(b):
        return isinstance(b, dict) and isinstance(b.get("fingerprint"), str) and isinstance(b.get("chars"), int) \
            and all(isinstance(b.get(k), list) and all(isinstance(h, str) for h in b[k]) for k in ("facts", "corrections"))
    if not isinstance(records, dict) or not all(
            isinstance(docs, dict) and all(good(b) for b in docs.values()) for docs in records.values()):
        raise ValueError(f"{MANIFEST.relative_to(ROOT)} is not in the expected form")
    return data


def save_baselines(entries: dict, keep=None):
    """Set the baseline of each record in `entries` ({id: {url: baseline}}); with `keep`, drop the others."""
    with manifest_lock:
        data = load_manifest() or {}
        records = data.get("records", {})
        records.update(entries)
        if keep is not None:
            records = {rid: docs for rid, docs in records.items() if rid in keep}
        out = {"note": "Written by pipeline/upstream.py, pipeline/daily.py and pipeline/extract.py; see upstream/README.md.",
               "records": {rid: dict(sorted(records[rid].items())) for rid in sorted(records)}}
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        tmp = MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(MANIFEST)


def baseline_from_cache(rec) -> dict:
    """Baselines of a record's documents from the cached texts: what a reader has just read."""
    docs = {}
    for url in sources(rec):
        found = cached(url)
        if found:
            docs[url] = baseline(*found)
    return docs


def baseline_from_seen(rec, seen: dict) -> dict:
    return {url: baseline(seen[url]["text"], seen[url]["links"]) for url in sources(rec) if "error" not in seen[url]}


def compare_all(records, seen, manifest) -> dict:
    base = (manifest or {}).get("records", {})
    return {rec["id"]: compare(rec, seen, base.get(rec["id"], {})) for _, rec in records}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="record what was read for every contest without a difference")
    args = ap.parse_args()

    failures = []
    try:
        manifest = load_manifest()
    except (ValueError, json.JSONDecodeError) as e:
        print(f"check not made: {e}")
        sys.exit(2)
    if manifest is None and not args.write:
        print(f"check not made: {MANIFEST.relative_to(ROOT)} is missing; run `pnpm upstream --write` once")
        sys.exit(2)

    records = list(watched())
    urls = sorted({u for _, rec in records for u in sources(rec)})
    seen = observe(urls)
    results = compare_all(records, seen, manifest)
    unread = {u for r in results.values() for u in r["unread"]}
    if urls and len(unread) > MAX_NOT_READ * len(urls):
        failures.append(f"{len(unread)} of {len(urls)} documents could not be read (the network, or a missing browser)")

    diffs = [(kind, rid, detail) for rid, r in results.items() for kind, detail in r["diffs"]]
    notes = [(kind, rid, detail) for rid, r in results.items() for kind, detail in r["notes"]]
    for kind, rid, detail in diffs:
        print(f"{kind}: {rid}: {detail}")
    for kind, rid, detail in notes:
        print(f"note: {kind}: {rid}: {detail}")
    closed = sum(1 for _, rec in records if (d := entry_deadline(rec)) and d[0] < TODAY)
    print(f"{len(records)} contests watched ({closed} closed within {GRACE_DAYS} days), {len(urls)} documents, "
          f"{len(urls) - len(unread)} read; {len(diffs)} differences, {len(notes)} notes.")

    if failures:
        for f in failures:
            print(f"check not made: {f}")
        sys.exit(2)
    if args.write:
        entries = {rec["id"]: baseline_from_seen(rec, seen) for _, rec in records
                   if not results[rec["id"]]["unread"]
                   and all(kind == "not in the manifest" for kind, _ in results[rec["id"]]["diffs"])}
        save_baselines(entries, keep={rec["id"] for _, rec in records})
        print(f"wrote {MANIFEST.relative_to(ROOT)}: {len(entries)} contests recorded")
        sys.exit(0)
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
