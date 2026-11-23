// Two checks shared by every site (see ../AGENTS.md, "Visible page"):
//
// - checkHeaderAndOutputs: the header links the first page of each top-level section of
//   the sidebar, in its order, and nothing else of the site's outputs; the page notes
//   (`.facts`) link the page's Markdown twin, the language's llms.txt and /index.json.
// - checkSelfReference: page text is about the subject, never about the page or the site.
//   It fails for a sentence that names the site or the page ("本站", "this site",
//   "このページ", "關於本站"), in the article, the hidden note and the page notes.
//   Code blocks are left out: a prompt or a command may say anything.
//
// Copy this file unchanged between sites; site-specific words go in `extra`.

export const SELF_REFERENCE = [
	/本站|本網站|本网站|(?<!版)本[頁页]|這一?頁|这一?页|此[頁页]/,
	/本サイト|当サイト|このサイト|このページ|本ページ/,
	/이 사이트|본 사이트|이 페이지|본 페이지/,
	/\b(this|our) (site|website|wiki|page)\b/i,
	/\bthe (site|website|wiki) (is|was|does|has|covers|lists|uses)\b/i,
];

/**
 * Fails unless the header links the first page of each top-level sidebar section, in
 * order (`sections`: hrefs), and the page notes link the page's Markdown twin, the
 * language's llms.txt and /index.json (`outputs`: hrefs; a missing one is skipped).
 */
export function checkHeaderAndOutputs(doc, id, fail, { sections, outputs }) {
	const nav = [...doc.querySelectorAll('header nav.sections a')].map((a) => a.getAttribute('href'));
	if (nav.join(' ') !== sections.join(' ')) fail(id, `header section links are [${nav.join(', ')}], expected [${sections.join(', ')}]`);
	for (const el of doc.querySelectorAll('header a[href]')) {
		if (/\.md$|llms\.txt$|index\.json$/.test(el.getAttribute('href'))) fail(id, `header links ${el.getAttribute('href')}; the other formats go in the page notes`);
	}
	const notes = new Set([...doc.querySelectorAll('main .facts a')].map((a) => a.getAttribute('href')));
	for (const href of outputs) if (href && !notes.has(href)) fail(id, `page notes do not link ${href}`);
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
