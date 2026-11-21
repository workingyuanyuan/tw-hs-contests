import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection } from 'astro:content';
import { LOCALES } from '../../lib/site.mjs';
import { llmsIndex } from '../../lib/llms.mjs';

export const prerender = true;

/** `/llms.txt` and the same index under each other language's prefix. */
export const getStaticPaths: GetStaticPaths = async () => {
	const docs = await getCollection('docs', (doc) => !doc.data.draft);
	return LOCALES.map((locale) => ({
		params: { dir: locale.dir || undefined },
		props: { text: llmsIndex(docs, locale) },
	}));
};

export const GET: APIRoute = ({ props }) =>
	new Response(props.text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
