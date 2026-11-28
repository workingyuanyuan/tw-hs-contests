// Two checks shared by every site (see ../AGENTS.md, "Visible page"):
//
// - checkHeaderAndOutputs: the header links the first page of each top-level section of
//   the sidebar, in its order, and nothing else of the site's outputs; the page notes
//   (`.facts`) link the page's Markdown twin, the language's llms.txt and /index.json.
// - checkSelfReference: page text is about the subject, never about the page or the site.
//   It fails for a sentence that names the site or the page ("本站", "this site",
//   "このページ", "關於本站"), in the article, the hidden note and the page notes.
//   Code blocks are left out: a prompt or a command may say anything.
//   It also fails for prose that names its source as the speaker ("官方介紹說",
//   "The official profile describes", "公式プロフィールでは"): state the fact, and let the
//   page notes name the source. Where sources disagree, name the other source
//   ("Prydwen and Game8 spell it Daffodil"). Quotations (blockquotes) are left out.
//
// - checkOpening: the answer line is the page's only opening. The body starts with a heading,
//   a table, a list, a quotation or an image, never with a paragraph of prose: a paragraph
//   there is a second opening, and it restates the answer line (owner decision, 2026-11-24).
//
// These patterns catch only phrasings already seen. Text about the page in other words, and a
// sentence that restates another, are left to the prose ledger (scripts/prose-review.mjs).
//
// Copy this file unchanged between sites; site-specific words go in `extra`.

export const SELF_REFERENCE = [
	/本站|本網站|本网站|(?<!版)本[頁页]|這一?頁|这一?页|此[頁页]/,
	/本サイト|当サイト|このサイト|このページ|本ページ/,
	/이 사이트|본 사이트|이 페이지|본 페이지/,
	/\b(this|our) (site|website|wiki|page)\b/i,
	/\bthe (site|website|wiki) (is|was|does|has|covers|lists|uses)\b/i,
];

/** Prose that names its source as the speaker instead of stating the fact. */
export const SOURCE_NAMING = [
	/(?:根據|依據|根据|依据|據|据)官方/,
	/官方(?:的)?(?:角色)?(?:介紹|介绍|簡介|简介|資料|资料|文件|文檔|文档|公告|說明|说明|網站|网站|設定|设定|描述)(?:中|裡|里)?(?:說|说|指出|形容|描述|表示|稱|称|寫道|写道|提到|提及|將|将|把|強調|强调)/,
	/公式(?:の)?(?:プロフィール|サイト|資料|ドキュメント|お知らせ|発表|紹介|説明)(?:では|によると|によれば)/,
	/공식\s?(?:프로필|문서|공지|사이트|자료|소개|설명)(?:은|는|에 따르면|에서는)/,
	/\b(?:the )?official (?:profile|introduction|description|notes|docs|documentation|announcement|site|website|page)s? (?:say|says|said|describe|describes|introduce|introduces|call|calls|state|states|place|places|spell|spells|note|notes|mention|mentions|explain|explains)\b/i,
	/\baccording to the official (?:profile|introduction|description|notes|docs|documentation|announcement|site|website|page)/i,
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

/** Fails for text in <main> (code blocks aside) that is about the site or the page, or that names its source as the speaker. */
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
	for (const el of copy.querySelectorAll('blockquote')) el.remove();
	const prose = copy.textContent.replace(/\s+/g, ' ');
	for (const pattern of SOURCE_NAMING) {
		const m = prose.match(pattern);
		if (m) {
			const at = Math.max(0, m.index - 30);
			fail(id, `prose names its source instead of stating the fact: …${prose.slice(at, m.index + m[0].length + 30).trim()}…`);
		}
	}
}

/** Fails when the body opens with a paragraph of prose instead of a heading, table, list, quotation or image. */
export function checkOpening(doc, id, fail) {
	const content = doc.querySelector('main .sl-markdown-content');
	if (!content || ![...content.children].some((el) => el.classList.contains('answer'))) return;
	for (const el of content.children) {
		if (el.matches('.agent-note, .answer, script, style, link, meta')) continue;
		if (el.tagName === 'P' && el.textContent.trim() && !el.querySelector('img, picture, svg')) {
			fail(id, `the body opens with a paragraph after the answer line; start it with a heading, table, list, quotation or image: ${el.textContent.trim().slice(0, 60)}…`);
		}
		break;
	}
}

// A fact that rests on one secondary source carries a numbered footnote (../AGENTS.md, Visible
// page): each note links a document that the page's `sources` lists, and each mark has its note.
export function checkFootnotes(doc, id, fail, sources) {
	const content = doc.querySelector('main .sl-markdown-content');
	if (!content) return;
	const notes = new Map([...content.querySelectorAll('section[data-footnotes] li[id]')].map((li) => [li.id, li]));
	for (const ref of content.querySelectorAll('a[data-footnote-ref]')) {
		if (!notes.has(ref.getAttribute('href').slice(1))) fail(id, `footnote ${ref.textContent} has no note`);
	}
	for (const [noteId, li] of notes) {
		const cites = [...li.querySelectorAll('a[href]')].some((a) => sources.some((s) => a.getAttribute('href').startsWith(s)));
		if (!cites) fail(id, `footnote ${noteId.replace(/^user-content-fn-/, '')} links no document in sources: ${li.textContent.trim().slice(0, 60)}`);
	}
}
