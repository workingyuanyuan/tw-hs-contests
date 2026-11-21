import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection } from 'astro:content';
import { pageMarkdown } from '../lib/page-md.mjs';

export const prerender = true;

/** One Markdown twin per page: `/contests/x/` -> `/contests/x.md`, `/` -> `/index.md`. */
export const getStaticPaths: GetStaticPaths = async () => {
	const docs = await getCollection('docs', (doc) => !doc.data.draft);
	return docs.map((entry) => ({
		params: { slug: entry.id },
		props: { markdown: pageMarkdown(entry) },
	}));
};

export const GET: APIRoute = ({ props }) =>
	new Response(props.markdown, { headers: { 'Content-Type': 'text/markdown; charset=utf-8' } });
