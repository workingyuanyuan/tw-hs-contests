# Rules for agents maintaining this site

A catalogue of contests that senior-high and vocational-high students in Taiwan can enter, at `https://yuanaruru.com/tw-hs-contests/` from the public repository `workingyuanyuan/tw-hs-contests`; a push to `main` deploys. Its readers are teachers and school staff, and the AI agents that work for them. The rules in `../AGENTS.md` apply; this file holds what is specific to this site and wins where it differs.

There is no schedule: an agent runs the daily update from a clone as `RUN.md` says and ends with `pnpm publish-daily`. Pages change only on such a run.

Read before the work: `RUN.md` before running the update; `pipeline/README.md` before changing a script or a source (how the scripts fetch, collect, read and write, how readings are scheduled, what other programs may read, verified pitfalls); `upstream/README.md` when `pnpm upstream` reports a difference. The question list and agent test results are in `tests/agent-eval/`.

## Decisions by the owner

- Goal: every contest in the country, all subjects. A goal, not a guarantee: `llms.txt` and the data files state which sources were read and how fresh each record is; page text does not.
- Included: a contest that has judging, gives a rank or a prize, and that senior-high or vocational-high students may enter, those limited to one county or city and those that need the school's nomination included. Not included: camps, certification exams, lectures, contests only for the students of one school, sports tournaments and meets (2026-11-24), and e-sports matches, where playing a video game decides the ranks (2026-11-25). A judged contest of game design or development is included, and so is a contest on a game platform where players score by answering questions on a subject.
- The catalogue holds facts only. Nothing here ranks, recommends or filters by suitability; whether a contest suits AI-assisted student work belongs to the daily report, a separate, private product that reads these records.
- A page needs supported facts on the deadline and on who may enter (`KEY_FACTS` in `pipeline/validate.py`; 2026-11-21).
- Readers are teachers who pass contests on to students in LINE groups, and students who land on one contest page from such a link (2026-11-21). Pages show the contest: what to do, the deadline, who may enter, deliverables, prizes, timeline. A fee is shown only when one is charged. Attendance and AI rules are not shown; they stay in the data files.
- A contest is open while a new entrant can still register (`entry_deadline` in `pipeline/validate.py`): the next registration deadline, else the next submission deadline, leaving out deadlines for entrants already through a round. It ends at its time, Taiwan time (`passed`). Then it moves to the archive (`/archive/<yyyy-mm>/`); its page keeps its address and says it is closed.
- When the organizer's documents contradict each other, the reader picks one version and the page says which (`conflict`, in the caveat).
- Registration links stay in the sources in the page notes (2026-11-21). The LINE share and copy buttons sit outside the article container (`src/components/Footer.astro`).
- Source text (2026-11-23): each fact keeps the short quote it was read from (`evidence[].quote`, a sentence or two), committed with its record and published in `/data/contests.json`. The full text of fetched documents is not committed (`cache/`).
- The catalogue finds contests itself (2026-11-24) and does not depend on the daily report. Scripts read the sources' list pages; models only judge (whether an announcement is a contest, what its documents say). A bounded web search may find the organizer's page or rules of a contest already found, never new sources to watch.
- Sources (2026-11-24): the 42 in `data/sources.json`. A source is added or removed only with the owner's approval. An ischool school whose `robots.txt` disallows `/*/widget/` is not read.
- The update runs from this repository alone, by any agent in any harness (2026-11-24). No step reads from or writes to a place outside the repository, and no step calls one vendor's command line: the scripts write the model work as task folders, and the agent running the update gives each to a fresh context. The repository sets no rule on which models read; `verification.readers` records them.
- No person reviews the content, on any day. Scripts are the only gate: a record read once publishes at level `checked`, and a second independent reading raises it to `verified` or withholds the page when the two disagree. Do not add a step that waits for a person.
- Following the sources (2026-11-22): the daily run reads a contest again when its documents changed; `pnpm upstream` only reports. No scheduled workflow and no issue, because an issue would wait for a person.
- One JSON file per contest edition in `data/contests/`, kept in git. Scripts are the only writers of these files.
- Traditional Chinese only, at the root; no translation step and no parity check.
- No "unofficial" label in the header (2026-11-23): contests have many organizers. `llms.txt` says once that the site is not the organizer of any contest and that each organizer's rules and corrections govern.
- Who lets a change go live: the owner confirms the look and changes to the generator; contest records go live without confirmation when the checks pass.
- Look (2026-11-20): "periodical". Serif headings (Noto Serif TC), body text in the system sans font, ink on paper, one red accent, hairlines and no boxes. Motion (2026-11-23): a soft pool of lamplight drifts behind the content; on arrival the title and the answer settle in like ink and the rule under the answer is drawn once. The mark before the site name is a red square, the end mark of a periodical's articles; it settles in like ink with the title (2026-11-25). Icon: a trophy. No Chinese character in either: 賽 reads as a rude word in Taiwanese.

## Choices made by agents

Not decided by the owner; change them when the work calls for it.

- The skin draws no text with CSS `content` but the brackets of a footnote mark and the glyph of its back link. Overrides: `MarkdownContent`, `ThemeSelect`, `SiteTitle` (the header links the three sidebar groups, 依截止月份, 依類別 and 封存) and `Footer`.

## Records

- `data/schema/contest.schema.json` defines a record. Field descriptions are in the schema; read it before writing a record.
- A record is one edition of one contest. A new year is a new record with a new `id`. An `id` never changes.
- Every fact carries `basis` and `evidence`. `quote`: the value is supported by sentences copied from the document without changes. `absent`: the listed documents were read in full and say nothing on the matter. `unread`: nothing was read, and the value must be `unknown` or `null`.
- Never fill a value from memory, from the title, or from last year's edition.
- A record does not state its own verification level. `pipeline/validate.py` computes it: `verified` (checks pass, two independent readings agreed), `checked` (checks pass, one reading), `unverified`.
- A record with no link at all is an error. An entry with no URL is not a record; it waits as a candidate until its page is found again.
- Do not copy personal contact details (contact person, phone, e-mail) into a record. Link the official page instead.
- The pages, `src/content/docs/` and `public/data/` are written by `pnpm pages` from the records. Do not edit them by hand; change the record or the generator.
- Other programs read `/data/contests.json` and write nothing in this repository; the catalogue reads nothing from them.

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
uv run -q --isolated --with jsonschema python -I pipeline/validate.py   # the record checks alone
```

A source marked `partial` or `failed` in a run is fixed in its entry in `data/sources.json`, not worked around. `work/` (task folders) and `cache/` are not committed.

## Pages

- The contract fields come from the record: `title`, `description` from `summary`, `appliesTo` from `edition`, `lastVerified`, `sources` from the documents read.
- A value that is `unknown`, or that rests on basis `absent`, is left out of the page. The page does not list unread documents and has no verification label; quotes are not shown. The data files keep all of it.
- A record whose level is `unverified` gets no page. It is in `data/contests.json` with `url: null`.
- Every link of a contest (official page, registration, rules, the announcement where it was found) is in `sources`, shown in the page notes. The body has no link list.
- The home page links index pages (by deadline month, by subject, the archive by month), and each index page lists its contests; contest pages are not in the sidebar, and the check script fails for a contest no index links.
- What the generator puts in `caveat`, in the index tables and at the top of the home page is in `pipeline/README.md`; limits on entry are on the contest page only.
- The answer line of a page is a fact: counts, the earliest deadline, the contest's summary (2026-11-21).
- Two editions of one contest may share a `description` (`mayShareDescription` in `scripts/check-dist.mjs`); their titles differ.
- Screenshots go in `../preview/tw-hs-contests/` (`b/` holds the current look).

## Where things are

| Path | Role |
| --- | --- |
| `data/contests/<id>.json`, `data/schema/` | One contest edition each; the definition of a record |
| `data/sources.json`, `data/discovered.json`, `data/candidates.json` | The sources; every announcement found; the queue of contests to read |
| `data/same-contests.json`, `data/stale/`, `data/runs/` | Pairs judged one edition or not; records that failed the checks (no page); the run summaries |
| `src/lib/site.mjs` | Site URL and sub-path, URL rules, `llms.txt` notes, labels |
