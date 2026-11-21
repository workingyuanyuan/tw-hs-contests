// Builds the Markdown twin of a page from its frontmatter and raw Markdown body.
// The same frontmatter fields feed the HTML facts block and the JSON-LD.

import { SITE, LABELS, localeOf, htmlPath, mdPathFromHtmlPath, llmsPath, isoDate } from './site.mjs';

/** Point internal links (`](/contests/2026-x/)`) at the absolute Markdown twin, and files at their absolute URL. */
export function rewriteInternalLinks(body) {
	return body.replace(/\]\((\/[^)\s#]*)(#[^)\s]*)?\)/g, (match, path, hash = '') => {
		if (/\.[a-z0-9]+$/i.test(path)) return `](${SITE}${path}${hash})`;
		return `](${SITE}${mdPathFromHtmlPath(path)}${hash})`;
	});
}

/**
 * Title, answer and facts of a page: everything above the body.
 * @param {{ id: string, body?: string, data: Record<string, any> }} entry
 */
export function pageHeader(entry) {
	const { id, data } = entry;
	const locale = localeOf(id);
	const t = LABELS[locale.lang];
	const facts = [];
	facts.push(`- ${t.appliesTo}: ${data.appliesTo}`);
	facts.push(`- ${t.caveat}: ${data.caveat}`);
	facts.push(`- ${t.lastVerified}: ${isoDate(data.lastVerified)}`);
	facts.push(`- ${t.page}: <${SITE}${htmlPath(id)}>`);
	facts.push(`- ${t.allPages}: <${SITE}${llmsPath(locale)}>`);
	facts.push(`- ${t.sources}:`);
	for (const s of data.sources) facts.push(`  - [${s.title}](${s.url})`);
	return [`# ${data.title}`, `> ${data.description}`, facts.join('\n')].join('\n\n');
}

/** The Markdown twin of a page: header, a rule, then the body. */
export function pageMarkdown(entry) {
	const body = rewriteInternalLinks((entry.body ?? '').trim());
	return [pageHeader(entry), '---', body].join('\n\n') + '\n';
}
