// The prose ledger, shared by every site (see ../AGENTS.md, "Acceptance"). Copy this file and
// scripts/prose-rubric.md unchanged between sites; site settings go in scripts/prose-site.mjs.
//
// Rules about page text that need judgment (text about the page or the site, a sentence that
// restates another, prose that names its source as the speaker) have no fixed wording, so a
// pattern catches only the phrasings already seen. A reader reads each unit of
// the site's own prose once; the units it passes are recorded, hashed, in reviews/prose-ledger.json.
// `pnpm verify` fails for a unit that is not in the ledger, so new or changed wording cannot go
// live unread. The deploy needs no model: it only compares hashes.
//
// A unit is the title, the answer line, the caveat, a heading, a table's header row,
// a long table cell, or a sentence of a paragraph or list item. Quotations, code, text the site
// shows as its source gives it (prose-site.mjs) and locales a script writes from another are not
// the site's prose and are left out. Before hashing, link texts that lead to the site's pages, the
// page's own names, quoted names and numbers are masked, so one template sentence is one unit on
// however many pages it appears. The rubric's hash is stored in the ledger: a changed rubric
// means every unit is read again.
//
//   node scripts/prose-review.mjs status                      unread units (after `pnpm build`)
//   node scripts/prose-review.mjs run [--jobs 4] [--limit N]   a reader reads them; passes are recorded
//   node scripts/prose-review.mjs accept <hash> <reason>       record a unit the reader flagged wrongly
//
// `run` prints each flagged unit with its page and the rule; fix the page, build, and run again.
// The reader is the shell command in PROSE_READER: it gets the prompt on stdin and prints its
// answer on stdout. Which model reads is the choice of the agent that runs it. A batch whose reader
// fails (a quota, a timeout) stays unread; run again later and only the unread units are read.

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { availableParallelism } from 'node:os';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';
import site from './prose-site.mjs';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const DIST = join(ROOT, 'dist');
const LEDGER = join(ROOT, 'reviews', 'prose-ledger.json');
const RUBRIC = fileURLToPath(new URL('./prose-rubric.md', import.meta.url));
const sha = (text) => createHash('sha256').update(text).digest('hex').slice(0, 16);
const squash = (text) => text.replace(/\s+/g, ' ').trim();
const CJK = /[぀-ヿ㐀-鿿가-힯]/;

/** Words of a text: a CJK character counts as one, a run of Latin letters or digits as one. */
const size = (text) => (text.match(/[぀-ヿ㐀-鿿가-힯]|[\p{L}\p{N}]+/gu) || []).length;

/** The pages of the built site, from dist/index.json: path below the base, language and contract fields. */
export function sitePages(dist = DIST) {
	const entries = JSON.parse(readFileSync(join(dist, 'index.json'), 'utf8'));
	const list = Array.isArray(entries) ? entries : entries.pages;
	const base = list.map((e) => new URL(e.url).pathname).filter((p) => p.endsWith('/')).sort((a, b) => a.length - b.length)[0];
	return list.map((e) => ({ ...e, path: new URL(e.url).pathname.slice(base.length), base }));
}

const derived = (path) => (site.derived || []).some((dir) => path === `${dir}/` || path.startsWith(`${dir}/`));

/**
 * A masker for names: every title and alias in dist/index.json, in any language. Names are
 * looked up by their first two characters, so a site with thousands of pages stays fast.
 */
export function nameMasker(pages) {
	const buckets = new Map();
	for (const p of pages) {
		for (const name of [p.title, ...(p.aliases || [])]) {
			if (!name || name.length < 2) continue;
			const key = name.slice(0, 2);
			if (!buckets.has(key)) buckets.set(key, new Set());
			buckets.get(key).add(name);
		}
	}
	const sorted = new Map([...buckets].map(([k, set]) => [k, [...set].sort((a, b) => b.length - a.length)]));
	return (text) => {
		let out = '';
		for (let i = 0; i < text.length; ) {
			const hit = (sorted.get(text.slice(i, i + 2)) || []).find((n) => text.startsWith(n, i));
			if (hit) {
				out += '⟨名⟩';
				i += hit.length;
			} else out += text[i++];
		}
		return out;
	};
}

/** Masks what varies between pages written from one template, so the unit hashes the same. */
export function mask(text, names = (t) => t) {
	return names(squash(text))
		.replace(/「[^」]*」|『[^』]*』|“[^”]*”|《[^》]*》|"[^"]*"/g, '⟨引⟩')
		.replace(/\d[\d.,:/\-–]*/g, '#');
}

function sentences(text) {
	return text
		.split(/(?<=[。！？])\s*|(?<=[.!?])\s+(?=\S)/)
		.map(squash)
		.filter(Boolean);
}

/** The units of the site's own prose on one built page, in reading order. */
export function unitsOf(doc, page, names = nameMasker([page])) {
	const skip = (site.skip?.(page.path, page.lang) || []).map(squash).filter((s) => s.length > 1).sort((a, b) => b.length - a.length);
	const out = [];
	const push = (kind, raw) => {
		let text = squash(raw || '');
		for (const s of skip) if (text.includes(s)) text = squash(text.split(s).join(' '));
		const masked = mask(text, names);
		if (size(masked.replace(/⟨[名引]⟩/g, '')) < (kind === 'cell' ? 8 : 3)) return;
		out.push({ kind, text, key: sha(masked) });
	};
	push('title', page.title);
	push('answer', page.answer);
	push('caveat', page.caveat);
	const content = doc.querySelector('main .sl-markdown-content');
	if (!content) return out;
	const copy = content.cloneNode(true);
	const drop = ['pre', 'script', 'style', 'blockquote', '.agent-note', '.answer', '.facts', '.not-found', '.sl-anchor-link', '.sr-only', ...(site.skipSelectors || [])];
	for (const el of copy.querySelectorAll(drop.join(','))) el.remove();
	// A link to one of the site's pages names that page; its text varies from page to page.
	for (const a of copy.querySelectorAll('a[href]')) {
		const href = a.getAttribute('href');
		if (href.startsWith(page.base) || href.startsWith('/') || href.startsWith('#')) a.textContent = '⟨名⟩';
	}
	for (const el of copy.querySelectorAll('h2, h3, h4, h5, h6, thead tr, td, p, li, dt, dd, figcaption')) {
		const tag = el.tagName.toLowerCase();
		if (/^h\d$/.test(tag)) push('heading', el.textContent);
		else if (tag === 'tr') push('table head', [...el.children].map((c) => squash(c.textContent)).join(' | '));
		else if (tag === 'td') push('cell', el.textContent);
		else {
			if (el.closest('li') && el.closest('li') !== el) continue;
			const own = el.cloneNode(true);
			for (const nested of own.querySelectorAll('ul, ol, table')) nested.remove();
			let text = squash(own.textContent);
			for (const s of skip) if (text.includes(s)) text = text.split(s).join(' ');
			for (const s of sentences(text)) push('sentence', s);
		}
	}
	return out;
}

function jsdom(html) {
	const virtualConsole = new VirtualConsole();
	return new JSDOM(html, { virtualConsole });
}

function loadLedger() {
	const rubric = sha(readFileSync(RUBRIC, 'utf8'));
	const ledger = existsSync(LEDGER) ? JSON.parse(readFileSync(LEDGER, 'utf8')) : { rubric, read: [], accepted: {} };
	const current = ledger.rubric === rubric;
	return { rubric, ledger, known: new Set(current ? [...ledger.read, ...Object.keys(ledger.accepted || {})] : []) };
}

function saveLedger(rubric, read, accepted) {
	mkdirSync(join(ROOT, 'reviews'), { recursive: true });
	const body = { rubric, read: [...new Set(read)].sort(), accepted: Object.fromEntries(Object.entries(accepted).sort()) };
	writeFileSync(LEDGER, JSON.stringify(body, null, '\t') + '\n');
}

/** The units of some pages, in order: [[page index, units], ...]. */
function unitsOfPages(dist, from, to) {
	const all = sitePages(dist);
	const names = nameMasker(all);
	const pages = all.filter((p) => !derived(p.path));
	const out = [];
	for (let i = from; i < Math.min(to, pages.length); i++) {
		const file = join(dist, pages[i].path, 'index.html');
		if (!existsSync(file)) continue;
		const dom = jsdom(readFileSync(file, 'utf8'));
		out.push([i, unitsOf(dom.window.document, pages[i], names)]);
		dom.window.close();
	}
	return out;
}

// jsdom keeps about 1 MB of every window it made, closed or not, until the thread ends: a site of
// 10,000 pages ran out of an 8 GB heap. Each batch of pages is read in a worker thread of its own,
// whose memory goes when it exits.
const PER_WORKER = 400;

/** Every page's units, with the page they first appear on. */
async function allUnits(dist = DIST) {
	const pages = sitePages(dist).filter((p) => !derived(p.path));
	const ranges = [];
	for (let i = 0; i < pages.length; i += PER_WORKER) ranges.push([i, i + PER_WORKER]);
	const results = [];
	const queue = [...ranges];
	await Promise.all(
		Array.from({ length: Math.max(1, Math.min(availableParallelism() - 1, 4)) }, async () => {
			while (queue.length) {
				const [from, to] = queue.shift();
				results.push(
					await new Promise((resolve, reject) => {
						const w = new Worker(new URL(import.meta.url), { workerData: { proseUnits: { dist, from, to } } });
						w.once('message', resolve);
						w.once('error', reject);
						w.once('exit', (code) => code && reject(new Error(`prose worker exited ${code}`)));
					})
				);
			}
		})
	);
	const units = new Map();
	for (const [i, list] of results.flat().sort((a, b) => a[0] - b[0])) {
		const page = pages[i];
		let prev = '';
		for (const u of list) {
			if (!units.has(u.key)) units.set(u.key, { ...u, page: page.path || '/', title: page.title, answer: page.answer, prev, pages: 0 });
			units.get(u.key).pages++;
			prev = u.text;
		}
	}
	return units;
}

/** For check-dist: fails for each page whose prose has units the ledger lacks. */
export async function checkProse(fail, dist = DIST) {
	const { known } = loadLedger();
	const units = await allUnits(dist);
	const unread = [...units.values()].filter((u) => !known.has(u.key));
	const byPage = new Map();
	for (const u of unread) byPage.set(u.page, [...(byPage.get(u.page) || []), u]);
	for (const [page, list] of byPage) {
		fail(page, `${list.length} unit(s) of prose not read (node scripts/prose-review.mjs run): “${list[0].text.slice(0, 70)}”`);
	}
}

function readerCommand(prompt) {
	return new Promise((resolve, reject) => {
		const child = spawn(process.env.PROSE_READER, { shell: true, cwd: ROOT, stdio: ['pipe', 'pipe', 'pipe'] });
		let stdout = '';
		let stderr = '';
		child.stdout.on('data', (d) => (stdout += d));
		child.stderr.on('data', (d) => (stderr = (stderr + d).slice(-400)));
		child.on('error', reject);
		child.on('close', (code) => {
			code === 0 && stdout.trim() ? resolve(stdout) : reject(new Error(`reader exited ${code}: ${squash(stderr).slice(-200)}`));
		});
		child.stdin.end(prompt);
	});
}

function parseAnswer(text, count) {
	const m = text.match(/\[[\s\S]*\]/);
	if (!m) throw new Error('no JSON array in the reader’s answer');
	const list = JSON.parse(m[0]);
	const byI = new Map(list.map((r) => [r.i, r]));
	return Array.from({ length: count }, (_, i) => byI.get(i));
}

async function run(args) {
	if (!process.env.PROSE_READER) {
		console.error('PROSE_READER is not set: a shell command that gets the prompt on stdin and prints the answer on stdout.');
		process.exit(2);
	}
	const jobs = Number(args[args.indexOf('--jobs') + 1]) || 4;
	const limit = args.includes('--limit') ? Number(args[args.indexOf('--limit') + 1]) : Infinity;
	const { rubric, ledger, known } = loadLedger();
	const read = ledger.rubric === rubric ? [...ledger.read] : [];
	const accepted = ledger.rubric === rubric ? { ...(ledger.accepted || {}) } : {};
	const pending = [...(await allUnits()).values()].filter((u) => !known.has(u.key)).slice(0, limit);
	console.log(`${pending.length} unit(s) to read`);
	const rules = readFileSync(RUBRIC, 'utf8');
	const batches = [];
	for (let i = 0; i < pending.length; i += 80) batches.push(pending.slice(i, i + 80));
	const flags = [];
	let done = 0;
	let failed = 0;
	const work = async (batch) => {
		const items = batch.map((u, i) => ({ i, page: u.page, title: u.title, answer: u.answer, before: u.prev, kind: u.kind, text: u.text }));
		const prompt = `${rules}\n\n## Units\n\n${JSON.stringify(items, null, 1)}\n`;
		let answers;
		for (let attempt = 0; attempt < 2 && !answers; attempt++) {
			try {
				answers = parseAnswer(await readerCommand(prompt), batch.length);
			} catch (e) {
				if (attempt) {
					failed += batch.length;
					console.error(`a batch failed twice; its units stay unread. ${e.message}`);
				}
			}
		}
		if (answers) {
			batch.forEach((u, i) => {
				const a = answers[i];
				if (a?.ok === true) read.push(u.key);
				else if (a) flags.push({ ...u, rule: a.rule, why: a.why });
			});
		}
		done += batch.length;
		saveLedger(rubric, read, accepted);
		console.log(`${done}/${pending.length} done: ${done - failed - flags.length} passed, ${flags.length} flagged, ${failed} failed`);
	};
	const queue = [...batches];
	await Promise.all(Array.from({ length: jobs }, async () => {
		while (queue.length) await work(queue.shift());
	}));
	mkdirSync(DIST, { recursive: true });
	writeFileSync(join(DIST, 'prose-flags.json'), JSON.stringify(flags, null, 1));
	for (const f of flags) console.log(`- ${f.page} [${f.rule}] ${f.text}\n  ${f.why} (${f.key}, on ${f.pages} page(s))`);
	console.log(`${flags.length} flagged, ${failed} not read (reader failed); the list is in dist/prose-flags.json`);
	if (failed) process.exitCode = 1;
}

if (!isMainThread && workerData?.proseUnits) {
	const { dist, from, to } = workerData.proseUnits;
	parentPort.postMessage(unitsOfPages(dist, from, to));
} else if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const [cmd, ...args] = process.argv.slice(2);
	if (cmd === 'status') {
		const { known } = loadLedger();
		const units = [...(await allUnits()).values()];
		const unread = units.filter((u) => !known.has(u.key));
		console.log(`${units.length} units, ${unread.length} unread`);
		for (const u of unread.slice(0, 20)) console.log(`- ${u.page} [${u.kind}] ${u.text.slice(0, 100)}`);
	} else if (cmd === 'run') {
		await run(args);
	} else if (cmd === 'accept' && args.length >= 2) {
		const { rubric, ledger } = loadLedger();
		saveLedger(rubric, ledger.rubric === rubric ? ledger.read : [], { ...(ledger.rubric === rubric ? ledger.accepted : {}), [args[0]]: args.slice(1).join(' ') });
		console.log(`accepted ${args[0]}`);
	} else {
		console.error('usage: node scripts/prose-review.mjs status | run [--jobs N] [--limit N] | accept <hash> <reason>');
		process.exit(2);
	}
}
