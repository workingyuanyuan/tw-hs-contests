#!/usr/bin/env bash
# Publish the daily update after its rounds (RUN.md): check the site, then commit and push the data
# and the pages. A push to main deploys the site.
#
# Usage: pnpm publish-daily
# Prints one last line that starts with "published:", "no change:" or "not published:".
set -uo pipefail
cd "$(dirname "$0")/.."
today=$(TZ=Asia/Taipei date +%F)

if [ -e work/todo.json ]; then
	echo "not published: tasks are waiting; run pnpm daily finish first"
	exit 1
fi
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
if ! git pull --rebase -q; then
	git rebase --abort 2>/dev/null
	echo "not published: git pull --rebase failed (the commit is kept locally)"
	exit 1
fi
if ! git push -q; then
	echo "not published: git push failed (the commit is kept locally)"
	exit 1
fi
echo "published: daily update $today (summary in data/runs/$today.json)"
