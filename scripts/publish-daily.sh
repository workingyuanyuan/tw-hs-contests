#!/usr/bin/env bash
# The daily update of the public catalogue, run after the daily report has written its snapshot
# (the last step of prompts/daily-collection.md in the daily report's repository):
# queue the snapshot's contests, re-check open ones, read new ones, write the pages, check the
# site, then commit and push. A push to main deploys the site.
#
# Usage: pnpm publish-daily [pipeline/daily.py options, for example --limit 10]
# Prints one last line that starts with "published:", "no change:" or "not published:".
set -uo pipefail
cd "$(dirname "$0")/.."
today=$(TZ=Asia/Taipei date +%F)

if ! git pull --ff-only -q; then
	echo "not published: git pull failed"
	exit 1
fi

uv run -q --isolated --with pymupdf --with playwright --with jsonschema python -I pipeline/daily.py "$@"
daily=$? # 1 when a record was left out of the pages; the other pages are written

if ! pnpm -s verify; then
	echo "not published: pnpm verify failed"
	exit 1
fi

git add data upstream/manifest.json src/content/docs public/data
if git diff --cached --quiet; then
	echo "no change: $today"
	exit 0
fi
git commit -q -m "data: daily update $today"
if ! git push -q; then
	echo "not published: git push failed (the commit is kept locally)"
	exit 1
fi
echo "published: daily update $today (pipeline exit $daily; summary in data/runs/$today.json)"
