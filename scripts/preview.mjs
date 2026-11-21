// Local preview of dist/ that sends the same Content-Type headers as GitHub Pages,
// including `charset=utf-8` for .md, .txt and .json. `astro preview` omits the
// charset, so a browser shows Chinese text in those files as garbage.
//
// Usage: pnpm preview [port]      (default port 4399)
// Build with the same SITE_URL sub-path that this server is started with.

import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BASE } from '../src/lib/site.mjs';

const DIST = fileURLToPath(new URL('../dist/', import.meta.url));
const PORT = Number(process.argv[2] ?? 4399);
const TYPES = {
	'.html': 'text/html; charset=utf-8',
	'.md': 'text/markdown; charset=utf-8',
	'.txt': 'text/plain; charset=utf-8',
	'.json': 'application/json; charset=utf-8',
	'.xml': 'application/xml',
	'.css': 'text/css; charset=utf-8',
	'.js': 'application/javascript; charset=utf-8',
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.jpg': 'image/jpeg',
	'.webp': 'image/webp',
	'.woff2': 'font/woff2',
};

async function resolve(urlPath) {
	const safe = normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, '');
	let file = join(DIST, safe);
	if (!file.startsWith(DIST.replace(/\/$/, ''))) return null;
	const info = await stat(file).catch(() => null);
	if (info?.isDirectory()) file = join(file, 'index.html');
	return (await stat(file).catch(() => null))?.isFile() ? file : null;
}

createServer(async (req, res) => {
	const { pathname } = new URL(req.url, 'http://localhost');
	// A project site lives under BASE; dist/ holds the files without that prefix.
	const inSite = pathname === BASE || pathname.startsWith(BASE + '/');
	const file = inSite ? await resolve(pathname.slice(BASE.length) || '/') : null;
	const target = file ?? join(DIST, '404.html');
	const body = await readFile(target).catch(() => Buffer.from('Not found'));
	res.writeHead(file ? 200 : 404, {
		'Content-Type': TYPES[extname(target)] ?? 'application/octet-stream',
	});
	res.end(req.method === 'HEAD' ? undefined : body);
}).listen(PORT, '127.0.0.1', () => {
	console.log(`Preview of dist/ at http://127.0.0.1:${PORT}${BASE}/`);
});
