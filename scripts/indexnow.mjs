// Prints the IndexNow request body for pages whose content changed, or nothing.
//
// Run after `pnpm verify` and before the deploy. A page counts as changed when its
// Markdown twin in dist/ differs from the live one (or the live one is missing). The
// twin is built from the content only, so a change to the skin submits nothing.
//
// The key file lives at the root of the domain (served by the user site), which
// authorizes every URL on the host, project sites included.
//
// Usage: node scripts/indexnow.mjs > body.json   (empty output: nothing to submit)
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { SITE as SITE_RAW } from '../src/lib/site.mjs';

const INDEXNOW_KEY = '633317ad5747c8e6a159c88e888ec920';
const SITE = SITE_RAW.replace(/\/+$/, '');
const DIST = 'dist';
const origin = new URL(SITE).origin;

const locs = readdirSync(DIST)
	.filter((f) => /^sitemap-\d+\.xml$/.test(f))
	.flatMap((f) => [...readFileSync(join(DIST, f), 'utf8').matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]));
if (locs.length === 0) throw new Error('indexnow: no URLs in dist/sitemap-*.xml');

/** `${SITE}/a/b/` -> `${SITE}/a/b.md`; the site root -> `${SITE}/index.md`. */
function twinUrl(loc) {
	const trimmed = loc.replace(/\/+$/, '');
	return (trimmed === SITE ? `${SITE}/index` : trimmed) + '.md';
}

const changed = [];
for (const loc of locs) {
	const twin = twinUrl(loc);
	const local = readFileSync(join(DIST, twin.slice(SITE.length + 1)), 'utf8');
	// 404 means a new page. Any other failure stops the run: an outage is not a change.
	const res = await fetch(twin, { signal: AbortSignal.timeout(15000) });
	if (!res.ok && res.status !== 404) throw new Error(`indexnow: ${twin} returned ${res.status}`);
	const live = res.ok ? await res.text() : null;
	if (live !== local) changed.push(loc);
}

console.error(`indexnow: ${changed.length} of ${locs.length} pages changed`);
for (const url of changed) console.error(`  ${url}`);
if (changed.length > 0) {
	console.log(
		JSON.stringify({
			host: new URL(SITE).host,
			key: INDEXNOW_KEY,
			keyLocation: `${origin}/${INDEXNOW_KEY}.txt`,
			urlList: changed,
		})
	);
}
