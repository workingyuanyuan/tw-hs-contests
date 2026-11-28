// Budgets of the AGENTS.md files (root AGENTS.md, "Writing these files"; RULES.md).
// One file, copied unchanged: as check-agents.mjs in the folder that holds the sites
// (checks its AGENTS.md and every site's; run by the pre-commit hook), and as
// scripts/check-agents.mjs in each site (checks that site's AGENTS.md; first in pnpm verify).
// Sizes are bytes of UTF-8: harnesses cut these files off by bytes.
// Exit 0: every file within its budget (warnings may be printed). 1: a file is over.
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT_BUDGET = 20000; // bytes, the AGENTS.md all sites share
const SITE_BUDGET = 12000; // bytes, a site's AGENTS.md
const WARN_FROM = 0.9; // of a budget: move something out before the next rule
const LINE_WARN = 800; // characters, one rule or one table row
const ON_DEMAND_WARN = 25000; // bytes, a file read before one kind of work
const ROOT_ON_DEMAND = ['RULES.md', 'START.md', 'STACK.md', 'LOOK.md', 'COMMUNITY.md', 'TESTS.md'];
const SITE_ON_DEMAND = ['SOURCES.md', 'RUN.md', 'pipeline/README.md', 'upstream/README.md'];

const here = dirname(fileURLToPath(import.meta.url));
const inSite = basename(here) === 'scripts';
const base = inSite ? dirname(here) : here;

const budgeted = [];
const onDemand = [];
if (inSite) {
	budgeted.push(['AGENTS.md', SITE_BUDGET]);
	onDemand.push(...SITE_ON_DEMAND);
} else {
	budgeted.push(['AGENTS.md', ROOT_BUDGET]);
	onDemand.push(...ROOT_ON_DEMAND);
	for (const entry of readdirSync(base, { withFileTypes: true })) {
		if (!entry.isDirectory()) continue;
		if (!existsSync(join(base, entry.name, 'AGENTS.md'))) continue;
		budgeted.push([join(entry.name, 'AGENTS.md'), SITE_BUDGET]);
		onDemand.push(...SITE_ON_DEMAND.map((file) => join(entry.name, file)));
	}
}

const bytes = (text) => Buffer.byteLength(text, 'utf8');
let failed = false;
const warnings = [];

for (const [path, budget] of budgeted) {
	const text = readFileSync(join(base, path), 'utf8');
	const size = bytes(text);
	const state = size > budget ? 'OVER' : size > budget * WARN_FROM ? 'near' : 'ok  ';
	console.log(`${state} ${String(size).padStart(6)} / ${budget} bytes  ${path}`);
	if (size > budget) failed = true;
	else if (size > budget * WARN_FROM) warnings.push(`${path}: ${budget - size} bytes left. Move a procedure or a section out before adding a rule.`);
	text.split('\n').forEach((line, i) => {
		const length = [...line].length;
		if (length > LINE_WARN) warnings.push(`${path} line ${i + 1}: ${length} characters. Does it hold more than one rule?`);
	});
}

for (const path of onDemand) {
	if (!existsSync(join(base, path))) continue;
	const size = bytes(readFileSync(join(base, path), 'utf8'));
	if (size > ON_DEMAND_WARN) warnings.push(`${path}: ${size} bytes. Dated reports of work belong in reviews/work-log.md; split the rest by the work that reads it.`);
}

for (const warning of warnings) console.log(`warn ${warning}`);
if (failed) {
	console.log('\nOver budget: move a whole procedure or section to a file read on demand; do not drop a condition or a qualifier to fit (RULES.md beside the shared AGENTS.md).');
	process.exit(1);
}
