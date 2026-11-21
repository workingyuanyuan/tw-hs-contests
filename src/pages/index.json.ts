import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { SITE, DATA_PATH, localeOf, htmlPath, mdPath, isoDate } from '../lib/site.mjs';

export const prerender = true;

/** Machine-readable list of every page, for agents that cannot run the site search. */
export const GET: APIRoute = async () => {
	const docs = await getCollection('docs', (doc) => !doc.data.draft);
	const pages = docs
		.map(({ id, data }) => ({
			title: data.title,
			answer: data.description,
			kind: data.kind,
			lang: localeOf(id).lang,
			url: SITE + htmlPath(id),
			markdown: SITE + mdPath(id),
			appliesTo: data.appliesTo,
			caveat: data.caveat,
			deadline: data.deadline ?? null,
			lastVerified: isoDate(data.lastVerified),
		}))
		.sort((a, b) => a.url.localeCompare(b.url));
	return new Response(JSON.stringify({ site: SITE, data: SITE + DATA_PATH, pages }, null, 2) + '\n', {
		headers: { 'Content-Type': 'application/json; charset=utf-8' },
	});
};
