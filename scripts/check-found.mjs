// "Being found" checks (../AGENTS.md) on the built site, called by check-dist.mjs.
// They fail when a search tool could not index a page or tell it from another.
//
//  a. Head: every page has a <title> and a meta description that no other page of its
//     language has, a canonical link to itself and, on a site with more than one
//     language, an hreflang link to the same page in each language.
//  b. Sitemap: lists every HTML page once and nothing else, each with the day the page
//     was last verified as its lastmod.

import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { JSDOM } from 'jsdom';
import { SITE, LOCALES, localeOf, idInLocale, htmlPath, isoDate } from '../src/lib/site.mjs';

/**
 * @param {string} DIST the built site
 * @param {{ id: string, data: Record<string, any> }[]} pages every page, as readPages() gives them
 * @param {(page: string, message: string) => void} fail records one problem
 * @param {{ mayShareDescription?: (page: { id: string, data: Record<string, any> }) => boolean }} [options]
 *   pages whose description another page may repeat (their titles must still differ)
 */
export function checkFound(DIST, pages, fail, { mayShareDescription = () => false } = {}) {
	const read = (path) => readFileSync(join(DIST, path), 'utf8');

	// a. Head
	const seen = { title: new Map(), description: new Map() };
	for (const page of pages) {
		const { id } = page;
		const file = (htmlPath(id) + 'index.html').slice(1);
		if (!existsSync(join(DIST, file))) continue; // check-dist.mjs reports the missing page
		const html = read(file);
		const head = new JSDOM(html.slice(0, html.indexOf('</head>') + '</head>'.length)).window.document;
		const own = {
			title: head.querySelector('title')?.textContent.trim(),
			description: head.querySelector('meta[name="description"]')?.getAttribute('content')?.trim(),
		};
		for (const [name, text] of Object.entries(own)) {
			if (!text) {
				fail(id, `no ${name} in <head>`);
				continue;
			}
			if (name === 'description' && mayShareDescription(page)) continue;
			const key = `${localeOf(id).lang}\n${text}`;
			if (seen[name].has(key)) fail(id, `same ${name} as ${seen[name].get(key)}: ${text}`);
			else seen[name].set(key, id);
		}
		if (head.querySelector('link[rel="canonical"]')?.getAttribute('href') !== SITE + htmlPath(id)) {
			fail(id, 'canonical link missing or not the page itself');
		}
		if (LOCALES.length > 1) {
			for (const other of LOCALES) {
				const link = head.querySelector(`link[rel="alternate"][hreflang="${other.lang}"]`);
				if (link?.getAttribute('href') !== SITE + htmlPath(idInLocale(id, other))) {
					fail(id, `no hreflang link to the ${other.label} version`);
				}
			}
		}
	}

	// b. Sitemap
	const indexFile = 'sitemap-index.xml';
	if (!existsSync(join(DIST, indexFile))) {
		fail(indexFile, 'missing');
		return;
	}
	/** URL -> lastmod, from every sitemap the index names. */
	const listed = new Map();
	for (const [, sitemapUrl] of read(indexFile).matchAll(/<loc>([^<]+)<\/loc>/g)) {
		const file = sitemapUrl.startsWith(SITE + '/') ? sitemapUrl.slice(SITE.length + 1) : null;
		if (!file || !existsSync(join(DIST, file))) {
			fail(indexFile, `names ${sitemapUrl}, which is not in dist/`);
			continue;
		}
		for (const [, entry] of read(file).matchAll(/<url>([\s\S]*?)<\/url>/g)) {
			const url = /<loc>([^<]+)<\/loc>/.exec(entry)?.[1].replaceAll('&amp;', '&');
			if (listed.has(url)) fail(String(url), 'listed more than once in the sitemap');
			listed.set(url, /<lastmod>([^<]+)<\/lastmod>/.exec(entry)?.[1]);
		}
	}
	const expected = new Map(
		pages.map(({ id, data }) => [SITE + htmlPath(id), data.lastVerified ? isoDate(data.lastVerified) : undefined])
	);
	for (const [url, verified] of expected) {
		if (!listed.has(url)) fail(url, 'page is not in the sitemap');
		else if (!verified || listed.get(url)?.slice(0, 10) !== verified) {
			fail(url, `sitemap lastmod is ${listed.get(url) ?? 'missing'}; the page was last verified on ${verified}`);
		}
	}
	for (const url of listed.keys()) {
		if (!expected.has(url)) fail(String(url), 'in the sitemap but not an HTML page of the site');
	}
}
