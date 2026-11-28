# How the catalogue is collected and written

What the scripts in this folder do, in the order a daily run uses them. `../RUN.md` says how an agent runs the update; `../AGENTS.md` holds the rules and decisions; each script's docstring has its options.

## Sources

- Which sources are read is the owner's decision (`../AGENTS.md`, Sources). How the 42 in `data/sources.json` came about: the 21 aggregators the daily report read stay, and 14 were added after measuring 66 candidate sources over 120 days of announcements: twelve senior-high and vocational schools' contest lists, the AIdea platform (where AI CUP topics are posted) and the K-12 Education Administration's notices. Together they found about 83% of the contests that all 66 found. City education bureaus were left out (mostly primary and junior-high contests), as were university research offices (mostly university contests) and sources with no contest in the period. Seven more are schools on the ischool school-site system, in counties no other source covers (Miaoli, Nantou, Kinmen) or with many vocational contests; their notice boards are read from the JSON the page loads (`read: "ischool"`). ischool schools whose `robots.txt` disallows `/*/widget/` are not read (中壢高中, 花蓮高工, 屏東高工 on 2026-11-24). A source is added or removed only with the owner's approval.

## Fetching documents

`fetch.py` reads HTML, plain text, PDF (PyMuPDF), `.docx`, `.pptx`, Google Docs, Sheets and Slides (exported as text), Google Drive files (downloaded) and folders (the file list). A page drawn by JavaScript is rendered in headless Chromium. bhuntr.com pages are read from their JSON-LD `Event` description. Images and the scanned pages of PDFs are read by OCR (`pipeline/ocr.py`, RapidOCR at a pinned version, in an environment of its own that `uv` provides); the original file is kept beside the text and put in the reader's folder, so that a reader who can view it compares the values with it. When OCR cannot run, the document counts as unread, not as empty. Old `.doc` files give no text; readers list them in `verification.unread`. A document whose server answers 404 or 410 is marked `gone` in the cache index until it is fetched again. The cache is keyed by the URL a reader clicks and hashed by the text, so a page whose markup changes on every request keeps its hash.

## Collection

`pnpm discover` (`pipeline/discover.py`) reads each source in `data/sources.json` page by page and records every announcement in `data/discovered.json` with its title, its date on the list and an outcome; how far it reads, why it stops and how a source is marked failed are in the script's docstring. Each run writes, per source, the pages read, the announcements seen and new, the oldest date and the stop reason to `data/runs/<date>.json`. A source marked `partial` or `failed` is fixed in its entry in `data/sources.json`, not worked around.

`pnpm daily prepare` then sorts the new announcements (`pipeline/triage.py`). An announcement whose address is already a candidate's or a record's is settled by the script. The rest go to triage tasks of up to 150 titles, alike titles in one batch: an agent marks each title a contest or not, names the contest, and points an announcement that repeats another (several schools post one contest) or a contest already known to it. The script queues one candidate per contest in `data/candidates.json`, with the links of all its announcements, and writes the outcome of each announcement in `data/discovered.json`. On its first run discovery found about 90 of the 92 open contests that the daily report had found from 2026-11-13 to 2026-11-20; the two it missed were on no list page it read.

A queued candidate is read in a task folder (`pipeline/extract.py`):

1. The script fetches the candidate's links, then the links in them most likely to be the rules, two hops deep and best first at each hop (`attachment_score`): a link whose text or file name shares the contest's own name, an attached file named 簡章, 辦法, 附件, 切結書 or FAQ, a short link text such as 官網. Two hops reach the rules when a school's announcement links the organizer's page or a Drive folder, which holds them. School pages carry site menus with Drive files and long news headlines; those score low and are not followed.
2. The folder `work/tasks/<key>-<reading>/` holds the texts, `pipeline/brief.md`, the schema, an example record and `check.py`, which runs the publishing checks. The agent writes `out.json`: a record, `{"need": [...]}` (once) or `{"skip": "..."}`, and its model's name in `model.txt`. It reads only its folder and never fetches.
3. First reading passes the checks: the record is written, method `single`, level `checked`. Says skip: the candidate is `skipped` with the reason. Asks for documents: the next round reads it again with them. Otherwise `failed`, tried once more in a later round.
4. A search task (`pipeline/search.py`, `pipeline/search.md`) is written once for a candidate whose links could not be fetched, whose two readings failed, or whose record has no checked deadline or eligibility (level `unverified`). An agent with a web search tool returns up to five links to the organizer's page or rules of that contest and edition, nothing else. The script fetches each and keeps it only when its text holds most of the contest's name and the edition (the 屆 number the name gives, else a year of the edition in Western or ROC form); the candidate is then read again. A candidate that still fails is `given_up`, and is read once more a week later while it may still be open.
5. A later round gives an open record read once to a second reading, in a fresh folder that holds nothing of the first. Both agree on the key facts (first deadline, who may enter, division, region, nomination): method `dual`, level `verified`. They disagree: method `disputed`, level `unverified`, no page; the note lists the differences. Attendance, fee and the AI rules are compared too, but a contradiction only removes that fact from the record (value `unknown`, basis `unread`, named in the note); it does not withhold the page.
6. Readers differ on which later steps count as deadlines, so the deadline compared is the one a new entrant must meet (`entry_deadline`), which the pages show.
7. The script, not the reader, sets `found_via`, `first_seen`, `updated`, `verification.last_verified`, `method` and `readers`. A reading joins an existing record when it reads that record again and names the same edition, or when the two share a link and name the same edition; organizers reuse a contest's page for the next edition. For the same reason a new candidate is settled by a shared link only with a record still open. Two records of one edition written under two ids are merged by `pnpm daily finish` when their titles match, letter case and years aside; a pair that the rules cannot settle (a shared contest page, or one title holding the other) is judged by the agent running the update and recorded in `data/same-contests.json`, which `finish` applies on every run (`pnpm daily same`, `distinct`).
8. `check.py` and `finish` apply the same rules to `out.json`: a reading cites only the documents in its folder, and asks for documents only from the links it was given.

`pnpm daily prepare` also re-checks the watched records once a day with the comparison of `pnpm upstream`. `pnpm daily finish` moves a record that fails the checks to `data/stale/` so that it is not published, and adds each round to `data/runs/<date>.json`; a record set aside is queued to be read again under its id and leaves `data/stale/` when a reading passes. A record whose documents are not in `cache/` (a fresh clone, a closed contest not fetched again) keeps the checks it passed when it was written; a reading just written must find every document there. A document marked `gone` fails the quotes taken from it in either case, so a record that rests on a removed document is set aside until it is read again.

`work/` holds the task folders and is not committed.

## Writing the pages

`pnpm pages` runs `pipeline/build_pages.py`. It checks every record (schema, file name, every quote present in the cached text of its document with whitespace ignored, every date present in its quote, at least one link), leaves out a record with an error and exits with 1. It replaces `src/content/docs/index.md`, `contests/`, `deadlines/`, `subjects/`, `archive/` and `public/data/`. Quotes stay in the data files; pages do not show them. Do not edit those by hand; change the record or the generator.

`pipeline/validate.py` runs the same checks alone: `uv run -q --isolated --with jsonschema python -I pipeline/validate.py`.

## Programs that read the catalogue

The daily report, and any other program, reads the catalogue's data and writes nothing in this repository. The catalogue reads nothing from them: it does not read the daily report's snapshots, and `pnpm publish-daily` fetches and reads nothing; it checks and pushes what the rounds of a run wrote (`RUN.md`).

- `https://yuanaruru.com/tw-hs-contests/data/contests.json` (`public/data/contests.json` in a clone): every record, open and closed, as published. `generated` is the date of the build. Each record carries `level` (`verified`, `checked`, `unverified`) and `url`, which is `null` for a record with no page. Fields are defined in `data/schema/contest.schema.json`; records carry `schema` (now 1). The facts pages leave out are here with their `basis`: `attendance`, `ai_policy`, a fee of none, `verification.unread`.
- Open or closed is not a field. A contest is open until its entry deadline passes: `entry_deadline` and `passed` in `pipeline/validate.py`, Taiwan time.
- Freshness: `data/runs/<date>.json` exists for each day a run discovered, and gives each source's pages read, announcements seen and new, and status (`ok`, `partial`, `failed`). `verification.last_verified` is the last day a record was read, or re-checked against unchanged documents.
- Contests found and not yet in a record: `data/candidates.json`; the statuses are in the docstring of `pipeline/candidates.py`.

## Verified pitfalls

- Links on school sites hold spaces and Chinese characters unescaped; `fetch.py` escapes them before the request.
- bhuntr.com pages of closed contests return 404; such a candidate fails and is given up after two tries.
- Inline tags split sentences in the extracted text ("作品須 至少使用 2 類不同 的"). Quotes are compared with all whitespace removed, so copy the sentence as it reads.
- A date followed by a time ("2026/11/27 23:59") must be matched before whitespace is removed, or the day runs into the hour.

## Scheduling of readings (agent's choices)

Not decided by the owner; change them when the work calls for it.

- A contest is read once in one round and again in a later round, so that a first reading publishes at level `checked` even when the runner stops there. Second readings go to open records, soonest deadline first, at most `--second` per round.
- A triage task judges titles only, once, and queues an announcement when its title does not tell. One first reading that says skip is final.

## Files a task folder gives its reader

| Path | Role |
| --- | --- |
| `pipeline/` | Fetch, discover, triage, read, search, validate, write pages (`pipeline/README.md`) |
| `pipeline/brief.md`, `pipeline/triage.md`, `pipeline/search.md`, `pipeline/example.json`, `pipeline/check_out.py` | What a task folder gives its reader: instructions, the example record, the self-check |

## What the page generator writes

- `caveat` is chosen by the generator in this order: closed, school nomination, limited region, judged together with older entrants, fee or deposit, else that dates and times are Taiwan time. A `conflict` in the record is added after it, or stands in place of the Taiwan-time sentence.
- Index tables have three columns (deadline, contest with its one-sentence summary, who may enter); limits on entry are on the contest page only. Deadline and subject indexes list open contests only; archive indexes list closed ones.
- The home page opens with one short list (deadline and name, `HOME_ROWS` rows) of contests closing within 14 days; the index links follow. More rows or columns push the index links past the first 5,000 characters.
