# Find the rules of one contest

A catalogue of contests for senior-high and vocational students has queued the contest named in `task.md`, but the documents it found do not give its rules. Find the organizer's own page or rules document for this contest and this edition. A script then fetches each link you give and keeps only those whose text names the contest and the edition; other agents read what it keeps.

## What you have in this folder

- `task.md`: today's date, the contest's name, its edition (屆) or the years it may carry, and the links already known.
- `check.py`: run `python3 check.py` after writing `out.json`. It prints every error.

## What to do

Search the web for the contest's name. Open the results you need to judge them. You need a web search tool; if you have none, write nothing and stop.

Give links, in order of preference, to:

1. the organizer's page for this edition (主辦單位's contest page or official site),
2. the rules document of this edition (簡章, 辦法, 實施計畫, 須知: PDF, Word, Google Drive),
3. the registration page.

Not: news reports, blogs, social media, sign-up forms (Google Forms), a school passing on the announcement, another edition (an earlier year or 屆), or another contest. Do not list links already in `task.md`. Do not look for other contests, and do not report them.

## What to write

Write the name of your model (the model ID, as exactly as you know it) in `model.txt`, one line.

Write `out.json`:

```json
{"urls": ["https://example.org/contest/2026/", "https://example.org/files/rules.pdf"]}
```

At most 5 links, each copied exactly from the address you opened. When you found nothing for this edition, write `{"urls": []}`.

Do not change any file except `out.json` and `model.txt`. Run `python3 check.py` until it prints `OK`.
