// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';
import starlightLinksValidator from 'starlight-links-validator';
import { sitemapOptions } from './src/lib/sitemap.mjs';
import { ORIGIN, BASE, TITLE, DESCRIPTION } from './src/lib/site.mjs';
import { satteri } from '@astrojs/markdown-satteri';
import { hastBase } from './src/lib/hast-base.mjs';

export default defineConfig({
	site: ORIGIN,
	base: BASE || undefined,
	trailingSlash: 'always',
	// Content links are written without the sub-path; this adds it in the HTML.
	markdown: { processor: satteri({ hastPlugins: [hastBase] }) },
	integrations: [
		// Added here so that it takes options; Starlight then leaves its own copy out.
		sitemap(sitemapOptions()),
		starlight({
			title: TITLE['zh-TW'],
			description: DESCRIPTION,
			defaultLocale: 'root',
			locales: { root: { label: '繁體中文', lang: 'zh-TW' } },
			// Contest pages are not in the sidebar: there will be too many. The index pages list them.
			sidebar: [
				{ label: '依截止月份', items: [{ autogenerate: { directory: 'deadlines' } }] },
				{ label: '依類別', items: [{ autogenerate: { directory: 'subjects' } }] },
				{ label: '封存', collapsed: true, items: [{ autogenerate: { directory: 'archive' } }] },
				{ label: '關於本站', items: [{ slug: 'about' }] },
			],
			customCss: ['@fontsource/noto-serif-tc/700.css', '@fontsource/noto-serif-tc/900.css', './src/styles/site.css'],
			components: {
				// The answer above the body and the page notes after it; one-click theme buttons.
				MarkdownContent: './src/components/MarkdownContent.astro',
				ThemeSelect: './src/components/ThemeSelect.astro',
				// LINE share and copy-announcement buttons on contest pages, outside the article.
				Footer: './src/components/Footer.astro',
			},
			routeMiddleware: './src/routeData.ts',
			credits: false,
			pagination: false,
			plugins: [
				starlightLinksValidator({
					exclude: ['/**/*.md', '/*.md', '/llms.txt', '/**/llms.txt', '/index.json', '/data/**'],
				}),
			],
		}),
	],
});
