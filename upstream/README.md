# Following the sources of this site

Each contest page is written from one record, and each fact of a record quotes the organizer's document it was read from (`evidence` in `data/contests/<id>.json`). Organizers extend deadlines, post corrected rules and remove files after a page is written. `pnpm upstream` fetches the documents of the watched contests again and compares them with what their records were read from.

```
pnpm upstream            # report. Exit 0: no difference. 1: differences. 2: the comparison could not be made
pnpm upstream --write    # also record what was read for every contest without a difference in upstream/manifest.json
```

It changes no record, page or cached text (`cache/`). The comparison is in `pipeline/upstream.py`; the daily run (`pipeline/daily.py`) uses the same comparison and acts on it, so the report shows what the next daily run will do.

## What is watched, and where the record is

The watched contests are those open, closed within the last 14 days (an extension can be announced after the deadline), or without a known deadline (`entry_deadline` in `pipeline/validate.py`). Their documents are the URL of each `evidence` entry and `links.official`.

| Watched | Compared with | Kept in |
| --- | --- | --- |
| Each quote of a record | The text of its document now, whitespace ignored | The records (`evidence[].quote`) |
| The lines of each document about dates, registration, fees, corrections or cancellation (`FACT_WORDS` in `pipeline/fetch.py`; counters and relative times are left out) | Short hashes of those lines in the text the record was read from | `manifest.json` (`facts`) |
| The links in each document whose text announces a change (更正, 修正, 勘誤, 延期, 補充, 異動, 取消, 停辦 …: `CORRECTION` in `pipeline/upstream.py`) | The same links in the text the record was read from | `manifest.json` (`corrections`) |
| The whole text of each document, without counters and whitespace | Its fingerprint and length | `manifest.json` (`fingerprint`, `chars`) |

The manifest holds hashes and lengths only, no text of the organizers' documents: the cache that holds their text is not committed. It is keyed by record id, then URL, and written by three scripts: `pipeline/extract.py` when it writes a record (from the texts the readers read), `pipeline/daily.py` when a re-check confirms a record, and `pnpm upstream --write`. Records that are no longer watched leave it.

Closed contests older than 14 days are not watched: their pages say they are closed, and organizers remove the files of past contests (bhuntr.com answers 404). A next edition announced on the same page is a new record, found by discovery, not a change to this one.

## The report

One line for each difference, then the notes, then a count. A line reads `kind: <record id>: detail`; the page is `/contests/<record id>/`.

| Line | Meaning | What the daily run does |
| --- | --- | --- |
| `quote gone` | A quote of the record is no longer in its document | Queues the contest to be read again under the same id. If the readings fail, the record fails the checks and moves to `data/stale/` (no page) |
| `source changed` | Lines about dates, registration or fees were added to or removed from a document (the first added line is shown) | Queues the contest to be read again |
| `correction posted` | A document has a new link whose text announces a change (a corrected 簡章, an extension) | Queues the contest to be read again |
| `document gone` | A document answers 404 or 410 | Queues the contest to be read again from its other links |
| `not in the manifest` | A document has no baseline: the record was written before the manifest, or its official page was never read | Confirms the record when its quotes are all there, and records the baseline |
| `not read for a week` | Some documents of the record could not be read, and the record was last read 7 or more days ago | Nothing; it keeps trying each day. Open the documents: a site that refuses scripts needs another way to read it (`BROWSER_HOSTS` in `pipeline/fetch.py`) |
| `note: not read` | A document could not be read this time (timeout, 403, 5xx), or its text fell below 30% of its length with none of its quotes (a sign-in or challenge page served with status 200) | Leaves the record as it is: no new `last_verified`, nothing queued |
| `note: text changed` | A document changed in lines that touch no fact (a menu, a news sidebar) | Confirms the record |

A contest queued for a change is read with every document of its record and, first, the links that announce the change. It is not queued again for the same change once its readings failed (`change` in `data/candidates.json`, a hash of every added or removed line and new link, so a second amendment is a new change); `pnpm upstream` keeps reporting it until a reading succeeds or the record leaves the watch.

`check not made` with exit 2 is not a report. "N of M documents could not be read" means more than a third failed: the network, or Chromium is missing (`pnpm exec playwright install chromium`). "manifest.json is missing": restore it from git, or run `pnpm upstream --write` once. "not in the expected form": restore it from git; to start over, delete it and run `pnpm upstream --write`.

## After updating

No person updates a page here: the daily run queues the contest to be read again, the readings and the checks decide, and `pnpm publish-daily` publishes (`RUN.md`; decisions in `AGENTS.md`). `--write` is for a baseline that is missing; a record with a difference or with a document not read is not recorded by it, so it cannot hide a change. It leaves with 0 whatever differences it reports (2, without writing, when the comparison could not be made); run `pnpm upstream` to see what is left.

## Schedule

None (owner, 2026-11-22). The daily run, which the owner starts by hand, makes this comparison every time and acts on it; an issue opened by a workflow would wait for a person, and the owner decided that no step waits for one. Whether GitHub's hosted runners can read the 57 hosts (school sites, Google Drive, bhuntr.com, some drawn by JavaScript) was not tested.
