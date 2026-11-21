# Agent test

Checks whether an agent with only a fetch tool answers a teacher's questions about contests better from this site than from the organizers' own pages.

## Files

| File | Role |
| --- | --- |
| `questions.json` | Ten questions with the expected answer, the qualifier that is easy to miss, and the page that holds them. Written from the organizers' documents (the quotes in the records, which the checks found in those documents), not from this site's pages |
| `fetch.mjs` | The fetch tool given to the agent. Modelled on the MCP reference Fetch server: main-article extraction, Markdown output, 5,000 characters per call, `start_index` to continue. Every call is logged to `runs/<run>.log` |
| `results/<date>/` | Fetch logs of each recorded run; the scores are below |

## How to run

1. Build the site with a local address and serve it (ports 4399–4401 belong to other sites):

```
SITE_URL=http://127.0.0.1:4417/tw-hs-contests pnpm pages
SITE_URL=http://127.0.0.1:4417/tw-hs-contests pnpm build
pnpm preview 4417
```

2. Give a fresh agent the questions (without the expected answers), the fetch command below as its only source, a start URL, and a budget of 3 fetches per question.

```
node tests/agent-eval/fetch.mjs --run <run-name> --q <question-id> <url> [start_index]
```

Start URL for this site: `http://127.0.0.1:4417/tw-hs-contests/`. Start URLs for the baseline: each contest's official page (`links.official` of its record, else its first rules document); for q08, `https://bhuntr.com/tw/competitions`.

3. Score each answer against `questions.json`: pass needs the answer and the qualifier; partial is one of the two; fail is a wrong or missing answer. Count fetches from the log, not from the reader's report.

4. Run `pnpm pages` and `pnpm verify` afterwards without `SITE_URL`, so that the pages and `dist/` carry the public address again.

## Results

### 2026-11-21

| Run | Pass | Partial | Fail | Fetches (from the log) |
| --- | --- | --- | --- | --- |
| This site, start URL `http://127.0.0.1:4417/tw-hs-contests/` | 9 (q02 used 4 fetches) | 1 (q08) | 0 | 19 |
| Organizers' pages | 1 (q05) | 2 (q01, q04) | 7 | 14 |

On the site:

- q02 (a contest closing in 2027-03, asked by name): the reader read `llms.txt` three times to find the page. A contest is listed by deadline month and subject, and `llms.txt` lists contest pages after its first 5,000 characters; a reader who does not know the month pages through `llms.txt`.
- q08: the reader found both music contests from the subject page but read only one contest page, so it missed that the other charges an entry fee. Index pages do not show fees.
- q09 passed because the conflict between the rules and the FAQ is in the caveat. Pages do not show AI rules otherwise; a question about AI rules of a contest without such a conflict would need the data file.

On the organizers' pages: 5 start pages returned almost no text (pages built by JavaScript, a footer only, a list frame), one returned 403 (`ibmi.pse.is`), and the 獎金獵人 list returned 59 characters. The readers of the official pages that did return text missed the qualifiers that sit in another document (q01: the other page with other dates).

Limits of this result:

- One reader model (Claude Sonnet, as a subagent) and one run per side.
- The questions and the expected answers were written by the author of the site, from the records' quotes.
- The site was served locally, built with `SITE_URL=http://127.0.0.1:4417/tw-hs-contests`.
- The baseline started from the official page of each contest, which a teacher would have to find first; with a search step its fetch count would be higher.
