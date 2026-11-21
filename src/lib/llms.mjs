// Builds each language's llms.txt and bundles from the content collection.
// Replaces starlight-llms-txt, which bundled the default language only and left
// out each page's caveat, dates and sources.

import { SITE, TITLE, LOCALES, LLMS_NOTES, DATA_PATH, localeOf, bareId, mdPath, llmsPath } from './site.mjs';
import { pageHeader, pageMarkdown } from './page-md.mjs';

/** Home page first, then hand-written pages, index pages, and contest pages, each by id.
    The index pages must fall within the first 5,000 characters; there are too many contests. */
function ordered(entries) {
	const group = { page: '1', index: '2', contest: '3' };
	const rank = (e) => (bareId(e.id) === 'index' ? '0' : (group[e.data.kind] ?? '1') + bareId(e.id));
	return [...entries].sort((a, b) => rank(a).localeCompare(rank(b)));
}

/** Site path of a bundle: `/llms-full.txt`, `/llms-small.txt` */
export function bundlePath(locale, set) {
	return `${locale.dir ? '/' + locale.dir : ''}/llms-${set}.txt`;
}

/**
 * A language's `llms.txt`. What a reader gets wrong without being told comes first,
 * then the bundles and the other languages, then one link per page. A fetch tool that
 * returns 5,000 characters must reach everything above the page list.
 */
export function llmsIndex(entries, locale) {
	const t = LLMS_NOTES[locale.lang];
	const [home, ...rest] = ordered(entries.filter((e) => localeOf(e.id) === locale));
	const pages = rest.map((e) => `- [${e.data.title}](${SITE}${mdPath(e.id)}): ${e.data.description}`);
	const more = [
		`- [${mdPath(home.id).slice(1)}](${SITE}${mdPath(home.id)}): ${t.home}`,
		`- [llms-full.txt](${SITE}${bundlePath(locale, 'full')}): ${t.full}`,
		`- [llms-small.txt](${SITE}${bundlePath(locale, 'small')}): ${t.digest}`,
		`- [contests.json](${SITE}${DATA_PATH}): ${t.data}`,
		`- [index.json](${SITE}/index.json): ${t.json}`,
		...LOCALES.filter((other) => other !== locale).map(
			(other) => `- ${t.otherLanguage} ${other.label}: <${SITE}${llmsPath(other)}>`
		),
	];
	return (
		[
			`# ${TITLE[locale.lang]}`,
			`> ${t.summary}`,
			`## ${t.heading}\n\n${t.notes.map((n) => `- ${n}`).join('\n')}`,
			`## ${t.more}\n\n${more.join('\n')}`,
			`## ${t.pages}\n\n${pages.join('\n')}`,
		].join('\n\n') + '\n'
	);
}

/** One language in one file. `full` keeps page bodies; `small` keeps the headers only. */
export function llmsBundle(entries, locale, set) {
	const pages = ordered(entries.filter((e) => localeOf(e.id) === locale));
	const render = set === 'full' ? (e) => pageMarkdown(e).trim() : (e) => pageHeader(e);
	return pages.map(render).join('\n\n\n') + '\n';
}
