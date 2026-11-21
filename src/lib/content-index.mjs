// Reads page frontmatter straight from disk, for scripts that run outside Astro
// (scripts/check-dist.mjs).

import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';

const DOCS_DIR = fileURLToPath(new URL('../content/docs/', import.meta.url));

function walk(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
		e.isDirectory() ? walk(join(dir, e.name)) : e.name.endsWith('.md') ? [join(dir, e.name)] : []
	);
}

/** Every page as `{ id, data }`, with ids matching the content collection ids. */
export function readPages() {
	return walk(DOCS_DIR)
		.map((file) => {
			const rel = relative(DOCS_DIR, file).replace(/\\/g, '/').replace(/\.md$/, '');
			const id = rel === 'index' ? 'index' : rel.replace(/\/index$/, '');
			const match = /^---\n([\s\S]*?)\n---/.exec(readFileSync(file, 'utf8'));
			return { id, data: match ? parse(match[1]) : {} };
		})
		.filter((page) => !page.data.draft)
		.sort((a, b) => a.id.localeCompare(b.id));
}
