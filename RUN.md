# Running the daily update

Any agent in any harness can run the update from a clone of this repository. It needs network access, Node with pnpm (`pnpm install` once), `uv` for Python, and Chromium for pages drawn by JavaScript (Playwright's, or the browser named in `CHROME_PATH`). Nothing is read from or written to a place outside the repository; `work/` and `cache/` are scratch and are not committed.

The scripts do every fetch, check and write. The model work (sorting announcements, reading a contest's documents) comes as task folders that the scripts prepare and then judge.

## Steps

1. `git pull --ff-only`
2. `pnpm daily prepare`. The first time in a day it also reads the sources' list pages and re-checks the open contests, which takes several minutes. It writes `work/TODO.md`.
3. Do every task listed in `work/TODO.md` as it says: each in a fresh context (a new subagent or session that has seen neither this conversation, nor another task, nor the records), with the prompt given there. Tasks may run at the same time. A search task needs an agent with a web search tool; without one, leave it, and it waits for a run that has one.
4. `pnpm daily finish`. It applies the tasks that were done, writes the pages, and says whether work is left.
5. While work is left and the budget allows, go back to step 2. A contest found today is queued in the first round, read in the second and read again in the third.
6. `pnpm build`, then `node scripts/prose-review.mjs run`. A reader of another model than the round's readers reads the pages' new wording (`PROSE_READER`: a command that takes the prompt on stdin and prints the answer, as the script's header shows). When it flags a unit, do not publish: report the unit and its page. A unit in a contest's wording that a reader wrote (the answer line, a deliverable, the prizes) is fixed by reading the contest again: `pnpm daily reread <id> ...`, then rounds from step 2 until the record has been read again, then this step again. The wording is the first reading's; a second reading confirms the facts only. A unit that a script writes for many pages is fixed in the script (`pipeline/build_pages.py`).
7. `pnpm publish-daily`. It runs `pnpm verify`, then commits and pushes; the push deploys the site. `pnpm verify` fails while a unit of the pages' wording is not in `reviews/prose-ledger.json`.

## Rules

- Never do a task in a context that saw another task, and never do one yourself in the context that runs these steps. The two readings of a contest must be independent; the script cannot tell when they are not. A harness that cannot start a fresh context does steps 1, 2, 4, 6 and 7 only: the re-check still confirms the open contests.
- Any model can do a task; the same model may do both readings of a contest. Each reader writes its model's name in `model.txt`, and the record keeps it.
- Do not edit a task's `out.json` or anything in `data/` by hand. When a task cannot be done, leave it: it comes back in a later round.
- To spend less, pass smaller numbers: `pnpm daily prepare --limit 10 --second 10 --triage 2 --search 3` (first readings, second readings, triage tasks of up to 150 announcements each, searches).
