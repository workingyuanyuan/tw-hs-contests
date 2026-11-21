import type { APIRoute } from 'astro';
import { SITE } from '../lib/site.mjs';

export const prerender = true;

// Content signals state how the content may be used after access:
// search = search indexes, ai-input = grounding AI answers, ai-train = model training.
// Crawlers read robots.txt at the domain root only. On a project site this file states
// the intent; the rule that binds is the one in the user site's robots.txt.
export const GET: APIRoute = () =>
	new Response(
		[
			'User-agent: *',
			'Content-Signal: search=yes, ai-input=yes, ai-train=no',
			'Allow: /',
			'',
			`Sitemap: ${SITE}/sitemap-index.xml`,
			'',
		].join('\n'),
		{ headers: { 'Content-Type': 'text/plain; charset=utf-8' } }
	);
