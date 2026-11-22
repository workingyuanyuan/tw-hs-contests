// Two checks shared by every site (see ../AGENTS.md, "Visible page"):
//
// - checkHeaderLinks: the header links the page's Markdown twin, the language's llms.txt
//   and /index.json, each with a data-key, and the built CSS draws the key hint
//   ("[M] ", "[L] ", "[J] ") before them from that attribute.
// - checkSelfReference: page text is about the subject, never about the page or the site.
//   It fails for a sentence that names the site or the page ("本站", "this site",
//   "このページ", "關於本站"), in the article, the hidden note and the page notes.
//   Code blocks are left out: a prompt or a command may say anything.
//
// Copy this file unchanged between sites; site-specific words go in `extra`.

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

export const SELF_REFERENCE = [
	/本站|本網站|本网站|(?<!版)本[頁页]|這一?頁|这一?页|此[頁页]/,
	/本サイト|当サイト|このサイト|このページ|本ページ/,
	/이 사이트|본 사이트|이 페이지|본 페이지/,
	/\b(this|our) (site|website|wiki|page)\b/i,
	/\bthe (site|website|wiki) (is|was|does|has|covers|lists|uses)\b/i,
];

/** Fails when the header of `doc` lacks one of the three output links. */
export function checkHeaderLinks(doc, id, fail, { markdown, llms, json }) {
	const want = [
		['M', markdown],
		['L', llms],
		['J', json],
	];
	for (const [key, href] of want) {
		if (!href) continue;
		const link = doc.querySelector(`header a[data-key="${key}"]`);
		if (!link) fail(id, `header has no [${key}] link`);
		else if (link.getAttribute('href') !== href) fail(id, `header [${key}] link points at ${link.getAttribute('href')}, not ${href}`);
	}
}

/** Fails unless some built CSS draws "[" attr(data-key) "]" before the header links. */
export function checkKeyHintCss(dist, fail) {
	const sources = [];
	const astro = join(dist, '_astro');
	if (existsSync(astro)) {
		for (const f of readdirSync(astro)) if (f.endsWith('.css')) sources.push(readFileSync(join(astro, f), 'utf8'));
	}
	// Small stylesheets are inlined into the HTML.
	if (existsSync(join(dist, 'index.html'))) sources.push(readFileSync(join(dist, 'index.html'), 'utf8'));
	const hint = /a[^{}]*::?before\s*\{[^}]*content:\s*['"]\[['"]\s*attr\(data-key\)/;
	if (!sources.some((css) => hint.test(css))) fail('_astro/*.css', 'no key hint drawn from data-key before the header output links');
}

/** Fails for text in <main> (code blocks aside) that is about the site or the page. */
export function checkSelfReference(doc, id, fail, extra = []) {
	const main = doc.querySelector('main');
	if (!main) return;
	const copy = main.cloneNode(true);
	for (const el of copy.querySelectorAll('pre, script, style')) el.remove();
	const text = copy.textContent.replace(/\s+/g, ' ');
	for (const pattern of [...SELF_REFERENCE, ...extra]) {
		const m = text.match(pattern);
		if (m) {
			const at = Math.max(0, m.index - 30);
			fail(id, `text about the site or the page: …${text.slice(at, m.index + m[0].length + 30).trim()}…`);
		}
	}
}
