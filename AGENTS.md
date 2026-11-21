# Rules for agents maintaining this site

This site is a catalogue of contests that senior-high and vocational-high students in Taiwan can enter. Its readers are teachers and school staff, and the AI agents that work for them. The rules in `../AGENTS.md` apply; this file holds what is specific to this site and wins where it differs.

Status on 2026-11-21: 92 records (87 with pages, 33 read twice), `pnpm verify` passes, and the agent test passed 9 of 10 on the site against 1 of 10 on the organizers' pages (`tests/agent-eval/README.md`). The owner approved the look "periodical" on 2026-11-20 and, on 2026-11-21, the redesign below: a catalogue that wins the attention of teachers and students, not a fact sheet in the daily report's terms. The git repository has a local commit on `main`; nothing is pushed or published.

## Decisions by the owner

- Goal: every contest in the country, all subjects. This is a goal, not a guarantee: the site states which sources were read and how fresh each record is.
- A page needs supported facts on the deadline and on who may enter (`KEY_FACTS` in `pipeline/validate.py`; owner, 2026-11-21).
- Readers are teachers who pass contests on to students in LINE groups, and students who land on one contest page from such a link (owner, 2026-11-21, after advice from three models). Pages show the contest: what to do, the deadline, who may enter, deliverables, prizes, timeline. A fee is shown only when one is charged. Attendance and AI rules are not shown: they were the owner's personal criteria for the daily report and stay in the data files.
- A contest is open while a new entrant can still register (`entry_deadline` in `pipeline/validate.py`): the next registration deadline, else the next submission deadline, leaving out deadlines for entrants already through a round. After it, the contest moves to the archive (`/archive/<yyyy-mm>/`); its page keeps its address and says it is closed.
- When the organizer's documents contradict each other, the reader picks one version and the page says which (`conflict`, in the caveat). Owner's decision.
- The docs-sites rules hold without exceptions (owner, 2026-11-21): registration links stay in the sources in the page notes, the sidebar layout stays. The LINE share and copy buttons sit outside the article container, like the theme buttons (`src/components/Footer.astro`).
- Sources stay the 21 second-hand aggregators of the daily report (owner, 2026-11-21): organizers hold a contest about once a year, so watching them daily costs reading quota for little; the aggregators already cover most contests. Do not add organizer or government sources to the daily run.
- The first reader (Gemini) reads every candidate. The second reader (Codex, about 45 long readings per quota window) reads at most `--second` open single-reader records per run, soonest deadline first.
- No person reviews the content, on any day. Scripts and a second independent reading are the only gates. Do not add a step that waits for a person.
- The catalogue holds facts only. Whether a contest suits AI-assisted student work is a separate, private product (`~/Projects/tw-highschool-ai-activity-daily`) that reads these records. Nothing here ranks, recommends or filters by suitability.
- A contest is included when it has judging, it gives a rank or a prize, and senior-high or vocational-high students may enter. Contests limited to one county or city, and contests that need the school's nomination, are included. Camps, certification exams and lectures are not.
- One JSON file per contest edition in `data/contests/`, kept in git. Scripts are the only writers of these files.
- Static files on GitHub Pages, in a public repository of its own. Name and address: `tw-hs-contests`, `https://workingyuanyuan.github.io/tw-hs-contests/`.
- Traditional Chinese only, at the root. There is no English version.
- Look (2026-11-20): "periodical". Serif headings (Noto Serif TC, SIL OFL, from `@fontsource/noto-serif-tc`, loaded in slices by `unicode-range`), body text in the system sans font, ink on paper, one red accent, hairlines and no boxes, light and dark themes. The skin draws no text with CSS `content`. Component overrides: `MarkdownContent`, `ThemeSelect`.

## Choices under "Decide per site" in `../AGENTS.md`

- Pages are produced from records: the source of a contest page is its JSON record, not hand-written Markdown. A script writes the Markdown page from the record; the contract fields come from the record: `title`, `description` from `summary`, `appliesTo` from `edition`, `caveat` from the fact a reader most likely misses (finalists must attend, entry fee, limited to one county, nomination needed), `lastVerified`, `sources` from the documents read.
- Languages: one, so there is no translation step and no parity check.
- The home page cannot link every contest within 5,000 characters. It links index pages (by deadline month, subject, region), and each index page lists its contests.
- Who lets a change go live: the owner confirms the look and the hand-written pages. Contest records go live without confirmation when the checks pass.

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
pnpm daily       # the daily run: queue, re-check, read new contests, write the pages (pipeline/daily.py)
pnpm queue       # add the contests of the newest daily-report snapshot to data/candidates.json
pnpm extract --limit 5 --key c0005      # read queued contests with the two readers (pnpm passes a `--` on to the script: leave it out)
pnpm fetch <url> [<url> ...]   # cache the text and links of a document
pnpm pages       # check the records, then write the pages and data files from them
pnpm verify      # build the site, then run the acceptance checks. Run this before you call a change done.
pnpm preview     # serve dist/ at http://127.0.0.1:4399/tw-hs-contests/ ; pass another port when 4399 is taken
```

`fetch.py` reads HTML, plain text, PDF (PyMuPDF), `.docx`, `.pptx`, Google Docs, Sheets and Slides (exported as text), Google Drive files (downloaded) and folders (the file list). A page drawn by JavaScript is rendered in headless Chromium. bhuntr.com pages are read from their JSON-LD `Event` description. Images, scanned PDFs and old `.doc` files give no text; readers list them in `verification.unread`. The cache is keyed by the URL a reader clicks and hashed by the text, so a page whose markup changes on every request keeps its hash.

## Collection

One search serves two products. The daily report (`~/Projects/tw-highschool-ai-activity-daily`, `DAILY_REPO`) finds contests and writes a snapshot that links every contest it saw: the graded ones, the excluded ones and a table of other contests for this catalogue (「目錄候選」). `pipeline/candidates.py` turns those links into the queue `data/candidates.json`; a contest seen again is matched by any shared link.

`pipeline/extract.py` reads one candidate:

1. The script fetches the candidate's links, then the links in them most likely to be the rules, one level deep and best first (`attachment_score`): a link whose text or file name shares the contest's own name, an attached file named 簡章, 辦法 or 附件, a short link text such as 官網. School pages carry site menus with Drive files and long news headlines; those score low and are not followed.
2. Two readers of different model families (`READERS`: Gemini via `agy`, GPT via `codex exec`) each get their own folder under `work/<key>/<model>/` with the texts, `pipeline/brief.md`, the schema, an example record and `check.py`, which runs the publishing checks. A reader writes `out.json`: a record, `{"need": [...]}` (once) or `{"skip": "..."}`. A reader never fetches and never sees the other's work.
3. A reading whose checks fail gets one more run with the errors.
4. Both pass and agree on the key facts (first deadline, who may enter, division, region, nomination): method `dual`, level `verified`. Both pass and disagree: method `disputed`, level `unverified`, no page; the note lists the differences. Attendance and fee are compared too, but a contradiction only removes that fact from the record (value `unknown`, basis `unread`, named in the note); it does not withhold the page. One passes: method `single`, level `checked`. Both skip: the candidate is `skipped` with the reason. Otherwise `failed`, tried once more on a later day.
5. A reader that reports a usage limit is not called again in the same run. Records read by one reader for that reason get the second reading in a later run (`second_readings`, part of `pipeline/daily.py`; `pnpm extract --limit 0 --second 15` alone).
6. Readers differ on which later steps count as deadlines, so the deadline compared is the first one, which the pages show.
7. The script, not the reader, sets `found_via`, `first_seen`, `updated`, `verification.last_verified`, `method` and `readers`.

`pipeline/daily.py` also re-checks open records: it fetches their documents again; unchanged text with passing checks moves `last_verified` to today; changed text queues the contest to be read again under the same id. A record that still fails is moved to `data/stale/` so that it is not published. Each run writes `data/runs/<date>.json`.

`work/` holds the readers' folders and is not committed.

`pnpm pages` runs `pipeline/build_pages.py`. It checks every record (schema, file name, every quote present in the cached text of its document with whitespace ignored, every date present in its quote, at least one link), leaves out a record with an error and exits with 1. It replaces `src/content/docs/index.md`, `contests/`, `deadlines/`, `subjects/`, `archive/` and `public/data/`. Quotes stay in the data files; pages do not show them. Do not edit those by hand; change the record or the generator. `about.md` is hand-written.

`pipeline/validate.py` runs the same checks alone: `uv run -q --isolated --with jsonschema python -I pipeline/validate.py`.

## Pages

- `caveat` is chosen by the generator in this order: closed, school nomination, limited region, judged together with older entrants, fee or deposit, else the deadline. A `conflict` in the record is added after it. It is shown in the page notes after the body and in the hidden note, as `../AGENTS.md` says.
- Pages state facts only ("No disclaimers about the page itself" in `../AGENTS.md`). A value that is `unknown`, or that rests on basis `absent` (the documents say nothing about a fee or about AI), is left out of the page. The page does not list unread documents and has no verification label. The data files keep all of it: `basis`, `verification.unread`, `level`.
- A record whose level is `unverified` gets no page. It is in `data/contests.json` with `url: null`.
- Every link of a contest (official page, registration, rules, the announcement where it was found) is in `sources`, shown in the page notes. The body has no link list.
- The home page says once that the site does not belong to any organizer; `llms.txt` says it too.
- Index tables have three columns (deadline, contest with its one-sentence summary, who may enter); limits on entry are on the contest page only. Deadline and subject indexes list open contests only; archive indexes list closed ones.
- The home page opens with two short lists (deadline and name, `HOME_ROWS` each): contests closing within 14 days and contests first seen in the last 7 days; the index links follow. More rows or columns push the index links past the first 5,000 characters, and `pnpm verify` fails.
- No sentence explains the site or the page (owner, 2026-11-21): the answer line of a page is a fact (counts, the earliest deadline, the contest's summary), and the not-an-organizer statement is said once, in the home page's caveat and in `llms.txt`.
- Contest pages are not in the sidebar. Every contest must be linked from an index page; the check script fails otherwise.
- Screenshots go in `../preview/tw-hs-contests/` (`b/` holds the current look; `options/` the four options shown to the owner). Headless Chromium has no Chinese font here: point `FONTCONFIG_FILE` at a config that adds `/mnt/c/Windows/Fonts`.

## Verified pitfalls

- `codex` (GPT reader) hit its usage limit after about 45 readings on 2026-11-20; the limit resets after some hours. Gemini via `agy` did not hit one in about 110 readings.
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
| `pipeline/candidates.py`, `data/candidates.json` | The queue of contests to read |
| `pipeline/extract.py`, `pipeline/brief.md`, `pipeline/check_out.py` | Two readers per contest; their instructions and self-check |
| `pipeline/daily.py`, `data/runs/` | The daily run and its summaries |
| `pipeline/validate.py` | Checks and verification level |
| `pipeline/build_pages.py` | Writes the pages and `public/data/` from the records |
| `cache/` | Text of fetched documents, not committed |
| `src/content/docs/about.md` | The only hand-written page |
| `src/lib/site.mjs` | Site URL and sub-path, URL rules, `llms.txt` notes, labels |
| `src/lib/page-md.mjs`, `src/lib/llms.mjs`, `src/pages/` | Markdown twins, `llms.txt`, bundles, `index.json`, `robots.txt` |
| `src/components/MarkdownContent.astro`, `src/components/ThemeSelect.astro`, `src/styles/site.css` | Answer above the body and page notes after it; theme buttons; the skin |
| `scripts/check-dist.mjs`, `scripts/preview.mjs` | Acceptance checks, local preview |
