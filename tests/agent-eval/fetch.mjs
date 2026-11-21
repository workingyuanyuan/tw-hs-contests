// A fetch tool for the agent test, modelled on the MCP reference Fetch server:
// HTML is reduced to its main article (Readability) and converted to Markdown;
// other text is returned raw; output is capped at 5,000 characters per call,
// with `start_index` to continue. Every call is appended to a log.
//
// Usage: node fetch.mjs --run <run-name> --q <question-id> <url> [start_index]
import { createRequire } from 'node:module';
import { appendFileSync, mkdirSync } from 'node:fs';
const require = createRequire(new URL('../../package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const { Readability } = require('@mozilla/readability');
const TurndownService = require('turndown');

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : undefined; };
const run = opt('--run') ?? 'run';
const q = opt('--q') ?? '?';
const [url, start = '0'] = args;
const MAX = 5000;
if (!url) { console.error('usage: node fetch.mjs --run <run> --q <id> <url> [start_index]'); process.exit(2); }

let text, status, type;
try {
  const res = await fetch(url, { headers: { 'User-Agent': 'agent-fetch-test/1.0', Accept: 'text/markdown, text/html;q=0.9, */*;q=0.8' }, redirect: 'follow' });
  status = res.status; type = res.headers.get('content-type') ?? '';
  const body = await res.text();
  if (type.includes('html')) {
    const dom = new JSDOM(body, { url });
    const article = new Readability(dom.window.document).parse();
    text = article?.content
      ? new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced' }).turndown(article.content)
      : dom.window.document.body?.textContent ?? '';
  } else text = body;
} catch (e) { status = 0; type = ''; text = `Fetch failed: ${e.message}`; }

mkdirSync(new URL('./runs/', import.meta.url), { recursive: true });
const from = Number(start) || 0;
const slice = text.slice(from, from + MAX);
const more = from + MAX < text.length;
appendFileSync(new URL(`./runs/${run}.log`, import.meta.url), JSON.stringify({ q, url, start: from, status, type, total: text.length }) + '\n');
console.log(`[status ${status}; ${type}; characters ${from}-${from + slice.length} of ${text.length}]\n`);
console.log(slice);
if (more) console.log(`\n[Content truncated. Call again with start_index=${from + MAX} to continue; that counts as another fetch.]`);
