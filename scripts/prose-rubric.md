# Reading a site's own prose

You read units of text from the pages of a documentation site. Each unit comes with its page's address, title and answer line (the one sentence shown under the title), and the unit just before it on the page. Judge only the text given: do not run commands or open files.

A unit is the page title, the answer line, the caveat (the qualifier a reader most likely misses), a heading, a table's header row, a table cell, or one sentence of a paragraph or list item. The text may be English, Chinese, Japanese or Korean. Quotations of the subject's own text have been removed.

Flag a unit when it breaks one of these rules. Otherwise pass it.

1. `about-page`: the text is about the page, the section or the site, not about the subject. This covers:
   - what the page, section or site covers, includes or is for ("with the full story text", "ストーリー全文つき", "each operator has a page", "the pages in this section");
   - how to use, search, sort or look things up on the page ("look them up by operator", "依幹員查找", "search the page for a product name", "sorted by English name");
   - a sentence whose only content is where on the site something is ("Headhunting rules are on [Headhunting]", "平台詳情見[平台與配備需求]", "see below"); a link on a term inside a sentence about the subject passes ("Arsenal Tickets are spent in [Arsenal Issues]", "cuts damage by 1% (see [Combat])");
   - what a table's columns or a list's items contain, said about the table rather than the subject ("each version has a number, a title and an update date", when it describes the table);
   - the criterion by which the site grouped its pages ("rules that do not change between versions", "不隨版本改變的規則");
   - headings and table headers that name parts of the site instead of the subject ("Pages", "本區頁面", "Related sections", "Question it answers", "回答的問題");
   - what the page leaves out, what a source fails to say, what is unverified, who runs the site, that it is unofficial.
   Notation is part of the fact and passes: which unit, time zone, version or edition values are in, and what a symbol or an abbreviation in a table means ("Times are UTC+8", "A dash means the facility needs no power"). So does a table header in general words ("Item | Detail"). The subject's own documents and sites (an official operator list, patch notes, the game's text in each language) are part of the subject: facts about them pass ("the official list shows two entries for one operator", "the editions do not always match line for line"). A heading or a link label that names a part of the subject passes. In a table or list that links other pages, a cell that names the things found there in the subject's own terms ("Thermal Banks, batteries, pylons and relays", "every version: number, title, update date") passes; a cell that speaks of the page itself ("one page per operator", "the page that answers…") fails. A verified absence in the subject itself ("the repository has no license file", "no enemy has arts resistance") is a fact and passes.
2. `restates`: the unit says again what the answer line or the unit just before it already says, in the same or other words, without adding a fact. A unit that repeats a name or a term while stating something new passes. A table header or cell that repeats a word of a heading passes.
3. `names-source`: the prose names its source as the speaker instead of stating the fact ("the official profile describes", "根據官方介紹", "公式プロフィールでは"). Naming a source passes where sources disagree or where one secondary source stands alone ("Prydwen and Game8 spell it Daffodil", "measured by player X on the NGA forum").
4. `addresses-reader`: the text speaks to agents or readers about reading the site ("for agents", "how to read this site").
5. `disclaimer`: a disclaimer or hedge about the site ("not affiliated", "may be inaccurate", "for reference only").

Answer with only a JSON array, one object per unit, in the order given:
`{"i": 0, "ok": true}` or `{"i": 0, "ok": false, "rule": "about-page", "why": "at most 20 words"}`.
