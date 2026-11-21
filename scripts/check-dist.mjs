// Acceptance checks on the built site in dist/. Run with `pnpm check` after `pnpm build`.
// Fails (exit 1) when an agent would get a worse page than a human does.
//
//  1. Pairing: every HTML page has a Markdown twin, an alternate link, a visible
//     link to the twin, and entries in llms.txt and index.json.
//  2. Clean Markdown: no JSX, no MDX imports, no `:::` directives.
//  3. First 5,000 characters: the answer, scope and caveat appear within the first
//     5,000 characters of the Markdown twin and of the text extracted from the HTML.
//  4. Equivalence: headings and code blocks extracted from the HTML match the twin.
//  5. No decoration leak: marks the skin draws with CSS must not appear in the
//     text extracted from the HTML.
//  6. Index coverage: the home page links every index page and the About page within its
//     first 5,000 extracted characters, and every contest page is linked from an index page.
//  7. Bundles: each language's llms-full.txt and llms-small.txt carry every page's
//     answer and caveat; a hidden pointer to the Markdown twin survives extraction.
//  8. llms.txt: notes, bundles and other languages within the first 5,000 characters.
//  9. The 404 page links each language's home page and page list.
// 10. robots.txt names the sitemap and carries a Content-Signal line.
// 11. Data files: data/contests.json lists every contest page, each with its own JSON file.
// Being found: title, description, canonical, hreflang and sitemap (scripts/check-found.mjs).

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import { Readability } from '@mozilla/readability';
import TurndownService from 'turndown';
import { SITE, LOCALES, LLMS_NOTES, DATA_PATH, localeOf, htmlPath, mdPath, llmsPath, withBase } from '../src/lib/site.mjs';
import { bundlePath } from '../src/lib/llms.mjs';
import { readPages } from '../src/lib/content-index.mjs';
import { checkFound } from './check-found.mjs';

const DIST = fileURLToPath(new URL('../dist/', import.meta.url));
const LIMIT = 5000;
const failures = [];
const fail = (page, message) => failures.push(`${page}: ${message}`);

const read = (path) => readFileSync(join(DIST, path), 'utf8');
const normalize = (text) => text.replace(/\s+/g, ' ').trim();

/** Fenced code blocks of a Markdown string, as trimmed strings. */
function codeBlocks(markdown) {
	return [...markdown.matchAll(/^```[^\n]*\n([\s\S]*?)^```/gm)].map((m) => m[1].trim());
}
/** ATX headings of a Markdown string outside code blocks, as `level text`. */
function headings(markdown) {
	const withoutCode = markdown.replace(/^```[^\n]*\n[\s\S]*?^```/gm, '');
	return [...withoutCode.matchAll(/^(#{1,6}) (.+)$/gm)].map((m) => `${m[1].length} ${m[2].trim()}`);
}

if (!existsSync(DIST)) {
	console.error('dist/ not found. Run `pnpm build` first.');
	process.exit(1);
}

const pages = readPages();
const kindOf = (page) => page.data.kind ?? 'page';
/** Contest page paths linked from the index pages. */
const linkedContests = new Set();
/** Each language's llms.txt, by locale. */
const llmsTxt = new Map(LOCALES.map((l) => [l, read(llmsPath(l).slice(1))]));
const indexJson = JSON.parse(read('index.json'));
const turndown = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced' });

// Every HTML file in dist must belong to a known page (or be the 404 page).
function htmlFiles(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
		e.isDirectory()
			? e.name.startsWith('_') || e.name === 'pagefind'
				? []
				: htmlFiles(join(dir, e.name))
			: e.name.endsWith('.html')
				? [relative(DIST, join(dir, e.name)).replace(/\\/g, '/')]
				: []
	);
}
const expectedHtml = new Set(pages.map((p) => (htmlPath(p.id) + 'index.html').slice(1)));
for (const file of htmlFiles(DIST)) {
	if (file !== '404.html' && !expectedHtml.has(file)) fail(file, 'HTML page without a content entry');
}

for (const { id, data } of pages) {
	const mdFile = mdPath(id).slice(1);
	const htmlFile = (htmlPath(id) + 'index.html').slice(1);
	if (!existsSync(join(DIST, htmlFile))) {
		fail(id, `missing HTML page ${htmlFile}`);
		continue;
	}
	if (!existsSync(join(DIST, mdFile))) {
		fail(id, `missing Markdown twin ${mdFile}`);
		continue;
	}
	const md = read(mdFile);
	const html = read(htmlFile);
	const dom = new JSDOM(html, { url: SITE + htmlPath(id) });
	const doc = dom.window.document;

	// 1. Pairing
	const alternate = doc.querySelector('link[rel="alternate"][type="text/markdown"]');
	if (alternate?.getAttribute('href') !== SITE + mdPath(id)) fail(id, 'missing or wrong <link rel="alternate" type="text/markdown">');
	if (!doc.querySelector(`main a[href="${withBase(mdPath(id))}"]`)) fail(id, 'no visible link to the Markdown twin inside <main>');
	if (!llmsTxt.get(localeOf(id)).includes(SITE + mdPath(id))) fail(id, `Markdown twin not listed in ${llmsPath(localeOf(id))}`);
	if (!indexJson.pages.some((p) => p.markdown === SITE + mdPath(id))) fail(id, 'page not listed in index.json');
	if (!doc.querySelector('script[type="application/ld+json"]')) fail(id, 'missing JSON-LD');

	// 7. Bundles and the pointer for agents
	for (const set of ['full', 'small']) {
		const bundle = normalize(read(bundlePath(localeOf(id), set).slice(1)));
		for (const text of [data.description, data.caveat]) {
			if (!bundle.includes(normalize(String(text)))) fail(id, `answer or caveat missing from ${bundlePath(localeOf(id), set)}`);
		}
			}
	const note = doc.querySelector('main .agent-note');
	if (!note?.textContent.includes(SITE + mdPath(id)) || !note.textContent.includes(SITE + llmsPath(localeOf(id)))) fail(id, 'missing hidden pointer to the Markdown twin and the page list');
	if (note && (note.hasAttribute('hidden') || note.getAttribute('aria-hidden') === 'true' || note.getAttribute('style'))) {
		fail(id, 'the pointer for agents must be hidden by CSS class only, or extractors drop it');
	}

	// 2. Clean Markdown
	const mdProse = md.replace(/^```[^\n]*\n[\s\S]*?^```/gm, '').replace(/`[^`\n]*`/g, '');
	if (/<[A-Z][A-Za-z]*[\s/>]/.test(mdProse)) fail(id, 'JSX component tag in Markdown twin');
	if (/^import\s.+from\s/m.test(mdProse)) fail(id, 'MDX import in Markdown twin');
	if (/^:::/m.test(mdProse)) fail(id, '`:::` directive in Markdown twin');

	// The answer under the title is one short sentence.
	const maxAnswer = 70;
	if (String(data.description).length > maxAnswer) fail(id, `description is ${String(data.description).length} characters; the limit is ${maxAnswer}`);

	// 3. First 5,000 characters
	const required = [
		['answer', data.description],
		['scope', data.appliesTo],
		['caveat', data.caveat],
	];
	const mdHead = normalize(md.slice(0, LIMIT));
	for (const [name, text] of required) {
		if (!mdHead.includes(normalize(String(text)))) fail(id, `${name} not within the first ${LIMIT} characters of the Markdown twin`);
	}
	// Worst case for HTML: a fetch tool that keeps the whole body, navigation included.
	for (const el of doc.querySelectorAll('script, style, template, svg')) el.remove();
	const bodyHead = normalize(doc.body.textContent).slice(0, LIMIT);
	for (const [name, text] of required) {
		if (!bodyHead.includes(normalize(String(text)))) fail(id, `${name} not within the first ${LIMIT} characters of the full HTML text`);
	}

	// 4. Equivalence, on the article that a readability-style extractor keeps.
	const article = new Readability(new JSDOM(html, { url: SITE + htmlPath(id) }).window.document).parse();
	const mainEl = doc.querySelector('main');
	const extracted = turndown.turndown(mainEl.innerHTML);
	const mdBody = md.slice(md.indexOf('\n---\n') + 5);
	const wantHeadings = headings(mdBody).map((h) => normalize(h.replace(/`/g, '')));
	const gotHeadings = headings(extracted)
		.filter((h) => !h.startsWith('1 '))
		.map((h) => normalize(h.replace(/\\/g, '').replace(/`/g, '')));
	if (JSON.stringify(wantHeadings) !== JSON.stringify(gotHeadings)) {
		fail(id, `headings differ between HTML and Markdown twin\n    md:   ${wantHeadings.join(' | ')}\n    html: ${gotHeadings.join(' | ')}`);
	}
	const wantCode = codeBlocks(mdBody).map(normalize);
	const gotCode = [...mainEl.querySelectorAll('pre')].map((pre) => {
		const lines = [...pre.querySelectorAll('.ec-line')];
		const text = lines.length ? lines.map((l) => l.textContent).join('\n') : pre.textContent;
		return normalize(text);
	});
	if (JSON.stringify(wantCode) !== JSON.stringify(gotCode)) {
		fail(id, `code blocks differ between HTML (${gotCode.length}) and Markdown twin (${wantCode.length})`);
		for (let i = 0; i < Math.max(wantCode.length, gotCode.length); i++) {
			if (wantCode[i] !== gotCode[i]) {
				failures.push(`    block ${i + 1}\n      md:   ${wantCode[i]}\n      html: ${gotCode[i]}`);
				break;
			}
		}
	}
	if (!article || !normalize(article.textContent).includes(normalize(String(data.description)))) {
		fail(id, 'a readability-style extractor does not keep the answer');
	}
	if (article && !article.textContent.includes(SITE + mdPath(id))) {
		fail(id, 'a readability-style extractor does not keep the pointer to the Markdown twin');
	}

	// 6. The home page links every index page and hand-written page within the first 5,000
	// characters an extractor returns. Contest pages are too many for that: each must be
	// linked from at least one index page instead.
	if (id === 'index') {
		const head = turndown.turndown(article?.content ?? '').slice(0, LIMIT);
		for (const other of pages) {
			if (other.id === id || kindOf(other) === 'contest') continue;
			if (!head.includes(htmlPath(other.id))) fail(id, `link to ${htmlPath(other.id)} is not within the first ${LIMIT} extracted characters of the home page`);
		}
	}
	if (kindOf({ data }) === 'index') {
		for (const a of mainEl.querySelectorAll('a[href]')) linkedContests.add(a.getAttribute('href'));
	}

	// 5. No decoration leak into extracted text.
	const visible = normalize(doc.body.textContent);
	for (const [name, pattern] of [
		// Add a pattern here for every piece of text the skin draws with CSS `content`.
		['bracketed key hint', /\[[A-Z]\]\s?[A-Za-z]/],
		['heading mark', /(^|\s)#{1,3} \S/],
		['list or table marker drawn by the skin', /[◆▶■█▮]\s/],
	]) {
		if (pattern.test(visible)) fail(id, `decoration leaked into page text: ${name}`);
	}
	// The skin draws a prompt before the page title and a two-digit counter before each
	// section heading. Neither may be typed into a heading.
	for (const h of doc.querySelectorAll('main h1, main h2, main h3')) {
		if (/^(>|\$|\d\d\s)/.test(h.textContent.trim())) fail(id, `decoration typed into a heading: ${h.textContent.trim().slice(0, 40)}`);
	}
}

for (const page of pages) {
	if (kindOf(page) === 'contest' && !linkedContests.has(withBase(htmlPath(page.id)))) fail(page.id, 'contest page is not linked from any index page');
}

// 8. llms.txt: what an agent must know before it answers, the bundles and the other
// languages all come within the first 5,000 characters, ahead of the page list.
for (const locale of LOCALES) {
	const name = llmsPath(locale);
	const head = llmsTxt.get(locale).slice(0, LIMIT);
	for (const note of LLMS_NOTES[locale.lang].notes) {
		if (!head.includes(note)) fail(name, `a note is not within the first ${LIMIT} characters`);
	}
	const links = [
		...['full', 'small'].map((set) => bundlePath(locale, set)),
		'/index.json',
		DATA_PATH,
	];
	for (const link of links) {
		if (!head.includes(`${SITE}${link}`)) fail(name, `link to ${link} is not within the first ${LIMIT} characters`);
	}
	const listed = pages.filter((p) => localeOf(p.id) === locale);
	const beyond = listed.filter((p) => !head.includes(SITE + mdPath(p.id))).length;
	if (beyond) console.warn(`note: ${name} lists ${beyond} of ${listed.length} pages beyond its first ${LIMIT} characters`);
}

// 9. A wrong URL is not a dead end: the 404 page links each language's home and page list.
const notFound = new JSDOM(read('404.html')).window.document;
for (const locale of LOCALES) {
	for (const href of [locale.dir ? `/${locale.dir}/` : '/', llmsPath(locale)].map(withBase)) {
		if (!notFound.querySelector(`main a[href="${href}"]`)) fail('404.html', `no link to ${href}`);
	}
}

// 10. robots.txt names the sitemap and states how the content may be used.
const robots = existsSync(join(DIST, 'robots.txt')) ? read('robots.txt') : '';
if (!robots.includes(`Sitemap: ${SITE}/sitemap-index.xml`)) fail('robots.txt', 'missing or without the sitemap');
if (!/^Content-Signal: /m.test(robots)) fail('robots.txt', 'no Content-Signal line');

// 11. Data files.
const dataFile = DATA_PATH.slice(1);
if (!existsSync(join(DIST, dataFile))) fail(dataFile, 'missing');
else {
	const data = JSON.parse(read(dataFile));
	const listed = new Set(data.contests.map((c) => c.id));
	for (const page of pages) {
		if (kindOf(page) !== 'contest') continue;
		const cid = page.id.replace(/^contests\//, '');
		if (!listed.has(cid)) fail(page.id, `not listed in ${DATA_PATH}`);
		if (!existsSync(join(DIST, 'data/contests', `${cid}.json`))) fail(page.id, 'no JSON file of its own under /data/contests/');
	}
	if (data.count !== data.contests.length) fail(dataFile, 'count does not match the number of contests');
}

checkFound(DIST, pages, fail);

if (failures.length) {
	console.error(`FAIL: ${failures.filter((f) => !f.startsWith('    ')).length} problem(s) in ${pages.length} pages\n`);
	for (const f of failures) console.error('- ' + f);
	process.exit(1);
}
console.log(`PASS: ${pages.length} pages, each with a Markdown twin; all checks passed.`);
