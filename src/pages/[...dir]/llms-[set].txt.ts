import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection } from 'astro:content';
import { LOCALES } from '../../lib/site.mjs';
import { llmsBundle } from '../../lib/llms.mjs';

export const prerender = true;

/** `/llms-full.txt`, `/llms-small.txt` and the same two under each other language's prefix. */
export const getStaticPaths: GetStaticPaths = async () => {
	const docs = await getCollection('docs', (doc) => !doc.data.draft);
	return LOCALES.flatMap((locale) =>
		['full', 'small'].map((set) => ({
			params: { dir: locale.dir || undefined, set },
			props: { text: llmsBundle(docs, locale, set) },
		}))
	);
};

export const GET: APIRoute = ({ props }) =>
	new Response(props.text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
