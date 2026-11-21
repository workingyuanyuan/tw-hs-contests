// Options for @astrojs/sitemap. Starlight adds that integration itself when the config
// has none; astro.config.mjs adds it with these options, so that every page in the
// sitemap carries `lastmod`. The language settings repeat what Starlight would pass.

import { SITE, LOCALES, htmlPath, isoDate } from './site.mjs';
import { readPages } from './content-index.mjs';

export function sitemapOptions() {
	/** `lastmod` of each page by its full URL: the day its facts were last verified. */
	const lastmod = new Map(
		readPages()
			.filter(({ data }) => data.lastVerified)
			.map(({ id, data }) => [SITE + htmlPath(id), isoDate(data.lastVerified)])
	);
	const i18n = {
		defaultLocale: 'root',
		locales: Object.fromEntries(LOCALES.map((l) => [l.dir || 'root', l.lang])),
	};
	return {
		...(LOCALES.length > 1 ? { i18n } : {}),
		serialize: (item) => ({ ...item, lastmod: lastmod.get(item.url) }),
	};
}
