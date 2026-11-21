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
