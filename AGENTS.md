# Rules for agents maintaining this site

This site is a catalogue of contests that senior-high and vocational-high students in Taiwan can enter. Its readers are teachers and school staff, and the AI agents that work for them. The rules in `../AGENTS.md` apply; this file holds what is specific to this site and wins where it differs.

Live since 2026-11-21 at https://yuanaruru.com/tw-hs-contests/, from the public repository workingyuanyuan/tw-hs-contests (a push to `main` deploys). There is no schedule: an agent runs the daily update from a clone as `RUN.md` says and ends with `pnpm publish-daily`. Pages change only on such a run. Agent test results are in `tests/agent-eval/README.md`.

## Decisions by the owner

- Goal: every contest in the country, all subjects. This is a goal, not a guarantee: `llms.txt` and the data files state which sources were read and how fresh each record is; page text does not.
- A page needs supported facts on the deadline and on who may enter (`KEY_FACTS` in `pipeline/validate.py`; owner, 2026-11-21).
- Readers are teachers who pass contests on to students in LINE groups, and students who land on one contest page from such a link (owner, 2026-11-21). Pages show the contest: what to do, the deadline, who may enter, deliverables, prizes, timeline. A fee is shown only when one is charged. Attendance and AI rules are not shown: they serve the daily report and stay in the data files.
- A contest is open while a new entrant can still register (`entry_deadline` in `pipeline/validate.py`): the next registration deadline, else the next submission deadline, leaving out deadlines for entrants already through a round. It ends at its time, Taiwan time (`passed` in `pipeline/validate.py`; `../AGENTS.md`, Research and provenance). After it, the contest moves to the archive (`/archive/<yyyy-mm>/`); its page keeps its address and says it is closed.
- When the organizer's documents contradict each other, the reader picks one version and the page says which (`conflict`, in the caveat). Owner's decision.
- Registration links stay in the sources in the page notes, and the sidebar layout stays as in `../AGENTS.md` (owner, 2026-11-21). The LINE share and copy buttons sit outside the article container, like the theme buttons (`src/components/Footer.astro`).
- Source text (2026-11-23): each fact keeps the short quote it was read from (`evidence[].quote`, a sentence or two), committed with its record and published in `/data/contests.json`. The full text of fetched documents is not committed (`cache/`).
- The catalogue finds contests itself (2026-11-24). It does not depend on the daily report; the daily report reads the catalogue's records. Scripts read the sources' list pages (`pnpm discover`, `data/sources.json`); models only judge (whether an announcement is a contest, what its documents say). A bounded web search may find the organizer's page or rules of a contest already found, never new sources to watch.
- Sources (owner, 2026-11-24): the 35 in `data/sources.json`. The 21 aggregators the daily report read stay, and 14 were added after measuring 66 candidate sources over 120 days of announcements: twelve senior-high and vocational schools' contest lists, the AIdea platform (where AI CUP topics are posted) and the K-12 Education Administration's notices. Together they found about 83% of the contests that all 66 found. City education bureaus were left out (mostly primary and junior-high contests), as were university research offices (mostly university contests) and sources with no contest in the period. A source is added or removed only with the owner's approval.
- The update runs from this repository alone, by any agent in any harness (2026-11-24). No step reads from or writes to a place outside the repository, and no step calls one vendor's command line: the scripts write the model work as task folders, and the agent running the update gives each to a fresh context (`RUN.md`). The repository sets no rule on which models read; two readings of a contest are independent when each runs in a fresh context, and `verification.readers` records the models.
- Following the sources (owner, 2026-11-22): the daily run reads a contest again when its documents changed; `pnpm upstream` only reports. No scheduled workflow and no issue, because an issue would wait for a person.
- No person reviews the content, on any day. Scripts are the only gate: a record read once publishes at level `checked`, and a second independent reading, when quota allows, raises it to `verified` or withholds the page when the two disagree. Do not add a step that waits for a person.
- The catalogue holds facts only. Whether a contest suits AI-assisted student work is a separate, private product (the daily report, in a repository of its own) that reads these records. Nothing here ranks, recommends or filters by suitability.
- A contest is included when it has judging, it gives a rank or a prize, and senior-high or vocational-high students may enter. Contests limited to one county or city, and contests that need the school's nomination, are included. Camps, certification exams and lectures are not.
- One JSON file per contest edition in `data/contests/`, kept in git. Scripts are the only writers of these files.
- Static files on GitHub Pages, in a public repository of its own. Name and address: `tw-hs-contests`, `https://yuanaruru.com/tw-hs-contests/`.
- Traditional Chinese only, at the root. There is no English version.
- No "unofficial" label in the header (2026-11-23): contests have many organizers and no single official source, so there is no official site to tell this one apart from. `llms.txt` says once that the site is not the organizer of any contest and that each organizer's rules and corrections govern (`../AGENTS.md`, Visible page).
- Look (2026-11-20): "periodical". Serif headings (Noto Serif TC, SIL OFL, from `@fontsource/noto-serif-tc`, loaded in slices by `unicode-range`), body text in the system sans font, ink on paper, one red accent, hairlines and no boxes, light and dark themes. Motion (2026-11-23): a soft pool of lamplight drifts behind the content over 90 s; on arrival the title and the answer settle in like ink and the rule under the answer is drawn once (`src/styles/site.css`, last block). Icon (`public/favicon.svg`): a trophy in paper colour on the light theme's red. No Chinese character: 賽 reads as a rude word in Taiwanese.

## Choices under "Decide per site" in `../AGENTS.md`

- Pages are produced from records: the source of a contest page is its JSON record, not hand-written Markdown. A script writes the Markdown page from the record; the contract fields come from the record: `title`, `description` from `summary`, `appliesTo` from `edition`, `caveat` from the fact a reader most likely misses (see `caveat` under Pages), `lastVerified`, `sources` from the documents read.
- Languages: one, so there is no translation step and no parity check.
- The home page cannot link every contest within 5,000 characters. It links index pages (by deadline month, by subject, and the archive by month), and each index page lists its contests.
- Who lets a change go live: there are no hand-written pages. The owner confirms the look and changes to the generator; contest records go live without confirmation when the checks pass.

## Choices made by agents

Not decided by the owner; change them when the work calls for it.

- A contest is read once in one round and again in a later round, so that a first reading publishes at level `checked` even when the runner stops there. Second readings go to open records, soonest deadline first, at most `--second` per round.
- A triage task judges titles only, once, and queues an announcement when its title does not tell. One first reading that says skip is final.
- The skin draws no text with CSS `content`. Component overrides: `MarkdownContent`, `ThemeSelect`, `SiteTitle` (the header links the three sidebar groups, 依截止月份, 依類別 and 封存, each to its first page) and `Footer` (LINE share and copy on contest pages).

## Records

- `data/schema/contest.schema.json` defines a record. Field descriptions are in the schema; read it before writing a record.
- A record is one edition of one contest. A new year is a new record with a new `id`. An `id` never changes.
- Every fact carries `basis` and `evidence`:
  - `quote`: the value is supported by sentences copied from the document without changes.
  - `absent`: the listed documents were read in full and say nothing on the matter (for example, no entry fee is mentioned).
  - `unread`: nothing was read. The value must be `unknown` or `null`.
- Never fill a value from memory, from the title, or from last year's edition.
- A record does not state its own verification level. `pipeline/validate.py` computes it: `verified` (checks pass, two independent readings agreed), `checked` (checks pass, one reading), `unverified`.
- A record with no link at all is an error. An entry from an old report that has no URL is not a record; it waits in a list of candidates until its page is found again.
- Do not copy personal contact details (contact person, phone, e-mail) into a record. Link the official page instead.
- `cache/` holds the extracted text of fetched documents and is not committed.

## Commands

```
pnpm daily prepare  # a round's tasks in work/TODO.md; the first round of a day also discovers and re-checks (pipeline/daily.py)
pnpm daily finish   # apply the tasks that were done, write the pages; says whether work is left
pnpm publish-daily  # verify, commit and push the data and pages (deploys). RUN.md has the whole update
pnpm upstream    # compare the documents of the watched contests with what their records were read from; changes nothing
pnpm discover    # read the sources' list pages; record every announcement in data/discovered.json
pnpm fetch <url> [<url> ...]   # cache the text and links of a document
pnpm pages       # check the records, then write the pages and data files from them
pnpm verify      # build the site, then run the acceptance checks. Run this before you call a change done.
pnpm preview     # serve dist/ at http://127.0.0.1:4399/tw-hs-contests/ ; pass another port when 4399 is taken
```

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
7. The script, not the reader, sets `found_via`, `first_seen`, `updated`, `verification.last_verified`, `method` and `readers`. A reading joins an existing record when it reads that record again and names the same edition, or when the two share a link and name the same edition; organizers reuse a contest's page for the next edition. For the same reason a new candidate is settled by a shared link only with a record still open.
8. `check.py` and `finish` apply the same rules to `out.json`: a reading cites only the documents in its folder, and asks for documents only from the links it was given.

`pnpm daily prepare` also re-checks the watched records once a day with the comparison of `pnpm upstream`. `pnpm daily finish` moves a record that fails the checks to `data/stale/` so that it is not published, and adds each round to `data/runs/<date>.json`; a record set aside is queued to be read again under its id and leaves `data/stale/` when a reading passes. A record whose documents are not in `cache/` (a fresh clone, a closed contest not fetched again) keeps the checks it passed when it was written; a reading just written must find every document there. A document marked `gone` fails the quotes taken from it in either case, so a record that rests on a removed document is set aside until it is read again.

`work/` holds the task folders and is not committed.

## When the sources change

Run `pnpm upstream` and read `upstream/README.md`.

## Writing the pages

`pnpm pages` runs `pipeline/build_pages.py`. It checks every record (schema, file name, every quote present in the cached text of its document with whitespace ignored, every date present in its quote, at least one link), leaves out a record with an error and exits with 1. It replaces `src/content/docs/index.md`, `contests/`, `deadlines/`, `subjects/`, `archive/` and `public/data/`. Quotes stay in the data files; pages do not show them. Do not edit those by hand; change the record or the generator.

`pipeline/validate.py` runs the same checks alone: `uv run -q --isolated --with jsonschema python -I pipeline/validate.py`.

## Pages

- `caveat` is chosen by the generator in this order: closed, school nomination, limited region, judged together with older entrants, fee or deposit, else that dates and times are Taiwan time. A `conflict` in the record is added after it (or stands alone, in place of the Taiwan-time sentence). It is shown in the page notes after the body and in the hidden note, as `../AGENTS.md` says.
- Page text is about the contests ("Visible page" in `../AGENTS.md`). A value that is `unknown`, or that rests on basis `absent` (the documents say nothing about a fee or about AI), is left out of the page. The page does not list unread documents and has no verification label. The data files keep all of it: `basis`, `verification.unread`, `level`.
- A record whose level is `unverified` gets no page. It is in `data/contests.json` with `url: null`.
- Every link of a contest (official page, registration, rules, the announcement where it was found) is in `sources`, shown in the page notes. The body has no link list.
- Index tables have three columns (deadline, contest with its one-sentence summary, who may enter); limits on entry are on the contest page only. Deadline and subject indexes list open contests only; archive indexes list closed ones.
- The home page opens with one short list (deadline and name, `HOME_ROWS` rows): contests closing within 14 days; the index links follow. More rows or columns push the index links past the first 5,000 characters, and `pnpm verify` fails.
- No sentence explains the site or the page (owner, 2026-11-21): the answer line of a page is a fact (counts, the earliest deadline, the contest's summary). The not-an-organizer statement is in `llms.txt` only.
- Two editions of one contest may share a `description` (`mayShareDescription` in `scripts/check-dist.mjs`); their titles differ.
- Contest pages are not in the sidebar. Every contest must be linked from an index page; the check script fails otherwise.
- Screenshots go in `../preview/tw-hs-contests/` (`b/` holds the current look; `options/` the four options shown to the owner). For Chinese in headless Chromium, see `../STACK.md` (Preview and screenshots).

## Verified pitfalls

- Links on school sites hold spaces and Chinese characters unescaped; `fetch.py` escapes them before the request.
- bhuntr.com pages of closed contests return 404; such a candidate fails and is given up after two tries.
- Inline tags split sentences in the extracted text ("作品須 至少使用 2 類不同 的"). Quotes are compared with all whitespace removed, so copy the sentence as it reads.
- A date followed by a time ("2026/11/27 23:59") must be matched before whitespace is removed, or the day runs into the hour.

## Where things are

| Path | Role |
| --- | --- |
| `data/schema/contest.schema.json` | Definition of a record |
| `data/contests/<id>.json` | One contest edition each |
| `pipeline/fetch.py` | Fetch a document and cache its text and links |
| `data/sources.json`, `pipeline/discover.py`, `data/discovered.json` | The sources, `pnpm discover`, and every announcement it found |
| `pipeline/triage.py`, `pipeline/triage.md` | Triage tasks: announcements into contests, one candidate per contest |
| `pipeline/candidates.py`, `data/candidates.json` | The queue of contests to read |
| `pipeline/extract.py`, `pipeline/brief.md`, `pipeline/check_out.py`, `pipeline/example.json` | Reading tasks; the readers' instructions; the self-check copied into every task folder; the example record they get (a fixed copy) |
| `pipeline/search.py`, `pipeline/search.md` | Search tasks: the organizer's page or rules of a queued contest, kept only when they name it and its edition |
| `pipeline/ocr.py` | Text of an image or a scanned PDF |
| `RUN.md`, `pipeline/daily.py`, `data/runs/`, `data/stale/` | How an agent runs the update; `pnpm daily prepare` and `finish`; the run summaries; records that failed the checks (no page) |
| `scripts/publish-daily.sh` | `pnpm publish-daily`: `pnpm verify`, commit and push |
| `.github/workflows/deploy.yml`, `scripts/indexnow.mjs` | Build, `pnpm verify`, deploy, then submit changed pages to IndexNow |
| `pipeline/upstream.py`, `upstream/` | `pnpm upstream`, the comparison the daily re-check uses; its README and manifest |
| `pipeline/validate.py` | Checks and verification level |
| `pipeline/build_pages.py` | Writes the pages and `public/data/` from the records |
| `cache/` | Text of fetched documents, not committed |
| `src/lib/site.mjs` | Site URL and sub-path, URL rules, `llms.txt` notes, labels |
| `src/lib/page-md.mjs`, `src/lib/llms.mjs`, `src/pages/` | Markdown twins, `llms.txt`, bundles, `index.json`, `robots.txt` |
| `src/components/MarkdownContent.astro`, `src/components/ThemeSelect.astro`, `src/styles/site.css` | Answer above the body and page notes after it, with the Markdown twin, `llms.txt` and `index.json` links; theme buttons; the skin |
| `src/components/SiteTitle.astro`, `src/components/Footer.astro` | Site name and section links; LINE share and copy |
| `scripts/check-dist.mjs`, `scripts/check-page-text.mjs`, `scripts/preview.mjs` | Acceptance checks (the second, copied unchanged from the reference site: section links, format links, no text about the site or the page), local preview |
| `src/lib/sitemap.mjs` | Sitemap options: `lastmod` of each page from `lastVerified` |
| `scripts/check-found.mjs` | Checks called by `check-dist.mjs`: a title and description of its own for every page, canonical, `hreflang`, sitemap |
| `tests/agent-eval/questions.json` | The site's question list: what readers ask, each with the expected answer and qualifier. The agent test and the search test draw from it |
