// Sätteri plugin: puts the site's sub-path in front of root-relative links and images
// (`/contests/2026-example/`, `/data/contests.json`), so content is written without it and
// still works on a GitHub Pages project site. The Markdown twins do not pass through
// here: src/lib/page-md.mjs turns the same links into absolute URLs.

import { defineHastPlugin } from 'satteri';
import { BASE } from './site.mjs';

export const hastBase = defineHastPlugin({
	name: 'site-base',
	element: {
		filter: ['a', 'img'],
		visit(node, ctx) {
			const key = node.tagName === 'a' ? 'href' : 'src';
			const value = node.properties?.[key];
			if (BASE && typeof value === 'string' && /^\/(?!\/)/.test(value)) {
				ctx.setProperty(node, key, BASE + value);
			}
		},
	},
});

// GFM footnotes come out with an English heading ("Footnotes"), English back-link labels and
// a "↩" glyph in the text. The heading is dropped (the twin has none, so the heading check
// would fail) and its name moves to the section's aria-label in the page's language; the
// glyph is drawn by CSS (`.data-footnote-backref::after`), since decoration is not page text.
const NOTES = {
	en: ['Notes', 'Back to reference'],
	'zh-tw': ['註解', '回到內文'],
	'zh-cn': ['注解', '回到正文'],
	ja: ['注', '本文に戻る'],
	ko: ['주석', '본문으로'],
};
const langOf = (url) => /\/src\/content\/docs\/(zh-tw|zh-cn|ja|ko)\//.exec(url?.pathname ?? '')?.[1] ?? 'zh-tw';

export const hastFootnotes = defineHastPlugin({
	name: 'footnotes-localised',
	element: {
		filter: ['section', 'h2', 'a'],
		visit(node, ctx) {
			const [label, back] = NOTES[langOf(ctx.fileURL)];
			const p = node.properties ?? {};
			if (node.tagName === 'section' && 'dataFootnotes' in p) {
				ctx.setProperty(node, 'id', 'footnote-label');
				ctx.setProperty(node, 'ariaLabel', label);
			} else if (node.tagName === 'h2' && p.id === 'footnote-label') {
				ctx.removeNode(node);
			} else if (node.tagName === 'a' && 'dataFootnoteBackref' in p) {
				ctx.setProperty(node, 'ariaLabel', `${back} ${String(p.href).replace(/^#user-content-fnref-/, '')}`);
				ctx.setField(node, 'children', []);
			}
		},
	},
});
