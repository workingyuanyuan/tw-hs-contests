// Site settings for scripts/prose-review.mjs (the prose ledger).
//
// - derived: locales a script writes from another. This site has one language.
// - skip(path, lang): text a page shows as its source gives it. Contest pages restate the
//   organizers' rules in the catalogue's own words; the organizers' sentences stay in the data
//   files as evidence quotes and are not shown on the pages, so nothing is skipped.

export default {
	derived: [],
	skip() {
		return [];
	},
};
