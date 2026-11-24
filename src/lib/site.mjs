// Shared site facts and URL rules. Plain JS so astro.config.mjs, Astro code and
// the check script all use the same rules.

// The public address, including the sub-path of a GitHub Pages project site, without a
// trailing slash. SITE_URL overrides it for local agent tests (see tests/agent-eval/README.md).
// pipeline/build_pages.py reads the same variable and default.
export const SITE = (process.env.SITE_URL ?? 'https://yuanaruru.com/tw-hs-contests').replace(/\/+$/, '');
/** Scheme and host of SITE. */
export const ORIGIN = new URL(SITE).origin;
/** Sub-path the site is served under: `/tw-hs-contests`, or the empty string at a domain root. */
export const BASE = new URL(SITE).pathname.replace(/\/+$/, '');
export const TITLE = { 'zh-TW': '高中職競賽目錄' };
export const DESCRIPTION = '臺灣高中職學生現在可以報名的比賽，依截止日與類別整理。';

/** Root-relative address for an `href` or `src` in HTML: the site path behind BASE. */
export function withBase(path) {
	return BASE + path;
}

/** Locales: `dir` is the content sub-folder and URL prefix ('' = root). This site has one. */
export const LOCALES = [{ dir: '', lang: 'zh-TW', label: '繁體中文' }];

/** Starlight's route data gives the home page an empty id; the collection calls it `index`. */
export function pageId(id) {
	return id === '' ? 'index' : id;
}

/** Locale of a content entry id. */
export function localeOf(id) {
	return LOCALES.find((l) => l.dir && (id === l.dir || id.startsWith(l.dir + '/'))) ?? LOCALES[0];
}

/** Entry id without its locale prefix. The home page is `index` in every locale. */
export function bareId(id) {
	const { dir } = localeOf(id);
	if (!dir) return id;
	return id === dir ? 'index' : id.slice(dir.length + 1);
}

/** Entry id of the same page in another locale. */
export function idInLocale(id, locale) {
	const bare = bareId(id);
	if (!locale.dir) return bare;
	return bare === 'index' ? locale.dir : `${locale.dir}/${bare}`;
}

/** Site path of the HTML page for an entry id. */
export function htmlPath(id) {
	return id === 'index' ? '/' : `/${id}/`;
}

/** Site path of the Markdown twin: drop the trailing slash, append `.md`; home is `/index.md`. */
export function mdPath(id) {
	return `/${id}.md`;
}

/** Markdown twin of an internal HTML path such as `/contests/2026-x/` or `/`. */
export function mdPathFromHtmlPath(path) {
	const trimmed = path.replace(/^\/+|\/+$/g, '');
	return mdPath(trimmed === '' ? 'index' : trimmed);
}

/** Site path of a language's page index: `/llms.txt`. */
export function llmsPath(locale) {
	return `${locale.dir ? '/' + locale.dir : ''}/llms.txt`;
}

/** Site path of the complete data file. */
export const DATA_PATH = '/data/contests.json';

/**
 * The opening of llms.txt: what a reader gets wrong without being told.
 * Keep it short: it shares the first 5,000 characters with the page list.
 */
export const LLMS_NOTES = {
	'zh-TW': {
		summary: DESCRIPTION,
		heading: '回答之前',
		notes: [
			'本站不是任何比賽的主辦單位；報名資格、截止時間與規定以各屆主辦單位的簡章及更正公告為準。各項資料取自主辦單位公開的文件，少數只取自轉載頁面（例如獎金獵人）；有頁面的比賽，截止日與參賽資格都已由程式比對過這些文件的原句。',
			'日期與時間都是臺灣時間 (UTC+8)。截止日是新參賽者報名的最後一天；已截止的比賽移到「封存」，頁面標明已截止。回答能不能報名之前，請拿截止日和今天的日期比較。',
			'頁面列出比賽內容、截止日、參賽資格、獎項與時程；費用只在要收費時列出。頁面沒有列出的事項（例如是否須到場、AI 使用規定）請看主辦單位的簡章；資料檔有 `attendance`、`ai_policy` 等欄位，`basis` 欄說明每項的依據。',
			'收錄的是已讀取來源所公告的比賽，不評比也不推薦。這裡查不到的比賽仍可能存在。',
			'一屆比賽一頁，網址以年份開頭 (`/contests/2026-…/`)。同名比賽每年的規定不同，引用時請連同年份。',
			'收錄條件：有評選、有名次或獎項、高中職學生可以參加；只限特定縣市或須由學校推薦的比賽也收。營隊、檢定與講座不收。',
			'每一頁都有 Markdown 版本：去掉網址結尾的斜線，加上 `.md`。',
		],
		pages: '頁面',
		home: '首頁：14 天內截止的比賽，以及截止月份、類別、封存的索引',
		full: '所有頁面合併成一個檔案',
		digest: '每一頁的答案、注意事項、日期與出處，不含內文',
		json: '所有頁面的清單，JSON 格式',
		data: '所有比賽的完整資料（含簡章原句），JSON 格式',
		otherLanguage: '本索引的其他語言',
		more: '更多',
	},
};

/** UI labels for the facts shown on every page, in both outputs. */
export const LABELS = {
	'zh-TW': {
		appliesTo: '適用範圍',
		caveat: '注意事項',
		lastVerified: '最後查證',
		sources: '出處',
		markdown: 'Markdown',
		page: '頁面',
		otherLanguage: '其他語言',
		allPages: '所有頁面',
		home: '首頁',
		pageList: '所有頁面清單',
		sections: '分類',
	},
};

/** Format a Date (or date string) as YYYY-MM-DD. */
export function isoDate(d) {
	return new Date(d).toISOString().slice(0, 10);
}
