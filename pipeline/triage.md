# Sort announcements into contests and the rest

You sort the titles of announcements that schools and contest sites posted. A script then queues every contest you mark, and other agents read its documents. Judge from the titles only.

## What you have in this folder

- `task.md`: today's date and how many items each file holds.
- `announcements.json`: the announcements, each with `n`, `title`, `source` (the site that listed it), `date` (when it was posted, or `null`) and `url`.
- `known.json`: contests already in the catalogue or its queue, each with a `ref` and a `title`.
- `check.py`: run `python3 check.py` after writing `out.json`. It prints every error.

Read only the files in this folder. Do not browse the web.

## What to write

Write `out.json`:

```json
{"items": [
  {"n": 1, "verdict": "contest", "name": "第8屆全國高中職AI專題競賽", "same_as": null, "deadline": null},
  {"n": 2, "verdict": "not", "why": "研習"},
  {"n": 3, "verdict": "contest", "name": "第8屆全國高中職AI專題競賽", "same_as": 1, "deadline": null}
]}
```

One item for every announcement, with its `n`.

- `verdict`: `"contest"` when the title announces a contest that may be open to senior-high or vocational-high students; `"not"` otherwise.
  - A contest: entries are judged and ranked or awarded. 競賽, 比賽, 大賽, 徵稿, 徵件, 徵選, 獎 calls, 挑戰賽, 黑客松, 創作獎, 選拔 with judging. A school passing on (轉知) another organizer's contest counts.
  - Not a contest: camps, lectures, workshops, courses, exams and certification, exhibitions, results and award lists, reports of a past event, an edition that has ended (its title gives a deadline before today, or a later edition of the same contest is in this file or in `known.json`), admissions, procurement, notices about the school itself, and contests only for teachers, primary or junior-high pupils, or university students.
  - Not a contest either: a contest only for the students of one school (校內 or 班際 in the title; a forwarded contest that asks 本校學生 to enter is not one), and sports tournaments and sports meets (錦標賽, 運動會, 聯賽, a sport's 盃賽). A call for writing, art or video about sport is a contest.
  - When the title does not tell, write `"contest"`. A reader will read its documents and drop it if it is not one. A contest you mark `"not"` is lost.
- `why` (for `"not"`): two to six words in Traditional Chinese, for example `研習`, `營隊`, `得獎名單`, `限國中`, `校內比賽`, `運動賽事`.
- `name` (for `"contest"`): the contest's own name as the title gives it, without 轉知, the school's name in front, or words such as 公告 and 附件.
- `same_as` (for `"contest"`): `null`, or:
  - the `ref` from `known.json` when the announcement is about that contest and edition, or
  - the `n` of an earlier announcement in this file about the same contest and edition.
  Two schools often post the same contest under different titles. Match on the contest's name and edition (屆, year), not on the school. When unsure whether two are the same, leave `same_as` null: a duplicate costs one more reading, a wrong match loses a contest.
- `deadline` (for `"contest"`): the registration or submission deadline as `YYYY-MM-DD` when the title states it, else `null`. Convert ROC years (115 年 = 2026). Never guess it.

Do not change any file except `out.json`. Run `python3 check.py` until it prints `OK`.
