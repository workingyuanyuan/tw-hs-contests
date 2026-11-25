# Read the documents of one contest and write its record

You are one of two readers who work independently. A script checks your work, so copy text exactly and leave out what you cannot support. Read only the files in this folder: the other reading, and the record if there is one already, must not be seen.

## What you have in this folder

- `task.md`: today's date, the contest name as a school's announcement wrote it (a hint, not a fact), and the list of documents.
- `docs/NN.txt`: the text of each document. The first lines give its URL and kind; the text follows the line `---`.
- `docs/NN.links.txt`: the links found in that document.
- `docs/NN.jpg`, `.png`, `.gif` or `.pdf`, beside a document whose kind ends in `-ocr` (an image or a scanned PDF): the original file. Its `docs/NN.txt` holds text read from it by OCR, which can misread characters and digits. If you can view the file, compare each value you take from the OCR text with it, and leave out a value the OCR text gets wrong. Quotes are still copied from `docs/NN.txt`.
- `schema.json`: the definition of a record. Read the descriptions of the fields.
- `example.json`: a correct record of another contest.
- `check.py`: run `python3 check.py` after writing `out.json`. It runs the same checks as the publishing script and prints every error.

## What to write

Write the name of your model (the model ID, as exactly as you know it) in `model.txt`, one line.

Write `out.json` with exactly one of these:

1. A record of this contest edition that follows `schema.json`.
2. `{"need": ["<url>", ...]}` when the rules are in a document you were not given and its link is in a `docs/NN.links.txt` file. At most 6 links, copied exactly. Ask only once; if you have asked before (`task.md` says so), write a record or a skip.
3. `{"skip": "<reason in Traditional Chinese>"}` when this is not a contest the catalogue includes, or no document describes it (a missing page, a page about something else).

The catalogue includes a contest when all three hold: entries are judged; it gives a rank, a prize or a certificate of award; senior-high or vocational-high students may enter. Contests limited to one county or city, or needing the school's nomination, are included. Camps, certification or proficiency exams, lectures, exhibitions without judging, and contests only for teachers, university students or adults are not. Nor are contests only for the students of one school, sports tournaments and sports meets (錦標賽, 運動會, 聯賽), and e-sports matches, where players or teams play a video game and the matches decide the ranks (電競賽); a contest open to the students of a county and to one school's own students is included, and so is a call for writing, art or video about sport, a judged contest of game design or development, and a contest on a game platform where players score by answering questions on a subject (a language, a school subject), even when it is called 電競賽 (PaGamO).

Do not browse the web. Do not change any file except `out.json`, `model.txt` and the `check/` folder that `check.py` writes.

## Rules for a record

- Facts only, from these documents only. Never from memory, from the title, or from another year's edition. A value the documents do not support is `null` or `"unknown"`.
- Write values in Traditional Chinese as the documents do; keep names exactly as written.
- Write what the documents say, never what they leave out: not 「金額未載」, 「未提及」 or 「未顯示於文件」. A value the documents do not give is left out of the sentence, or the fact is `unknown`.
- Every fact carries `basis` and `evidence`:
  - `quote`: each evidence item has the document's `url` (from the first line of its `docs/NN.txt`) and a `quote` copied from the text after `---`, character for character, without changing punctuation or full-width and half-width forms. Copy a whole clause or sentence, at most about 150 characters. Do not join text from two places into one quote; use two evidence items.
  - `absent`: the documents were read in full and say nothing about it. Evidence lists the documents read, `url` only, no `quote`. Use it for `fee`, `attendance`, `ai_policy` and `prizes` only:
    - `fee`: when the full rules describe how to register and mention no fee, the value is `none` with basis `absent`.
    - `attendance`: when the full rules describe judging of submitted work and no event that entrants attend, the value is `none` with basis `absent`. An award ceremony alone is not attendance.
    - `ai_policy`: when the rules say nothing about AI, the value is `not_mentioned` with basis `absent`.
    - Use `unknown` instead when the rules you have are incomplete: only a poster, a summary page, or rules that refer to a document you could not read for these matters.
  - `unread`: nothing was read on this; the value must be `unknown` or `null` and `evidence` is `[]`.
- Dates: ISO `YYYY-MM-DD`. Convert ROC years (115 年 = 2026, 116 年 = 2027). The quote of a date must contain its month and day as written, so quote the line that holds the date. `time` is `HH:MM` (24-hour) or `null`.
- `dates` holds every dated step: registration and submission deadlines, shortlist announcement, final event, result announcement. When a document gives a range, the deadline is its last day. A `label` says what happens on the date and, when it holds for some entrants only, for whom (「金門縣參賽隊伍決賽報名截止」); never which document gives it (not 「（某某公告）」).
- `eligibility.levels`: everyone who may enter (`國小`, `國中`, `高中`, `高職`, `五專`, `大專`, `研究所`, `社會人士`…), not only senior-high students.
- `eligibility.division`: `hs_only` when only senior-high and vocational students may enter; `separate` when senior-high and vocational students have a division of their own; `mixed` when they are judged in one division with other entrants, older (university students, adults) or younger (junior-high or primary pupils); a "學生組" open to every level of school is `mixed`; `unknown`.
- `eligibility.regions`: `["全國"]` unless the documents limit entry to named counties, cities or schools; an entry open to anyone in or outside Taiwan is also `["全國"]`.
- `eligibility.nomination`: `school` when entry needs the school's selection or nomination; `none` when the documents describe students registering themselves or their team; `unknown` when they say neither.
- `summary`: one sentence of at most 70 characters: who does what and hands in what. It opens the contest's page, and `deliverables` is listed under it: name the work in general terms (its kind and subject), and leave the stages, forms and the way it is handed in (online, by post, on site) to `deliverables`, so that no deliverable says only what the summary says.
- `title`: the official name without the organizer in front. `organizers`: each with role `主辦`, `承辦`, `協辦` or `指導`.
- `categories`: one to three values from the list in the schema.
- `id`: the edition's year, a hyphen, then a short ASCII key of lower-case letters, digits and hyphens, for example `2026-thu-smart-sustainability`. The year is the year of the registration deadline.
- `links.official`: the organizer's own page for this contest, when it is among the documents or their links. `links.rules`: rule documents (PDF and the like) with a short title. `links.registration`: the registration address when a document gives it.
- `verification.unread`: the names of documents that the rules refer to and that you could not read (a form, an annex, an image without text). `verification.note`: `null`.
- `conflict`: when the organizer's documents contradict each other on a fact, say so in one or two sentences, naming each document and the value it gives. Write about the documents only, never about the record, the page or the site (not 「本紀錄採……」, 「本頁採……」 or 「本站……」); the page itself shows the value the record follows. Otherwise leave the field out.
- Do not copy personal contact details (a contact person's name, phone, e-mail) anywhere, not even inside a quote. The check fails on them.
- The script fills these; write them as placeholders: `"found_via": []`, `"first_seen"` and `"updated"` today, `"verification.last_verified"` today, `"verification.method": "single"`, `"schema": 1`.

When `python3 check.py` prints errors, fix `out.json` and run it again until it prints `OK`. A quote that the check cannot find was not copied exactly: copy it again from the `docs/NN.txt` file.
