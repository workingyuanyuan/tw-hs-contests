"""Search tasks: find the organizer's page or rules of one contest already queued.

pipeline/daily.py calls this module; it has no command of its own.

A search is bounded: it looks for documents of a contest the queue already holds, never for new
contests. `write_task` writes a folder (work/tasks/<key>-s/) with pipeline/search.md, the contest's
name, edition hints and the links already known, and check.py. The agent searches the web and
writes out.json: {"urls": [...]}, at most MAX_URLS links. `finish` fetches each link and keeps it
only when its text names the contest (most of the bigrams of its name) and the edition (the 屆
number the name gives, as the first 屆 the text names, else a year of the edition, in Western or ROC
form). Links to private or local addresses are refused before anything is fetched. Kept links join the
candidate as rules and it is read again; when none is kept, it takes the status in `after_search`
(given_up, or done for a record that only lacked a checked fact). A candidate is searched once.
"""
import ipaddress
import json
import re
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as cq  # noqa: E402
from extract import CONTESTS, NOT_DOCS, PIPELINE, bigrams, get, title_core  # noqa: E402

TODAY = cq.TODAY
MAX_URLS = 5
NAME_SHARE = 0.6  # share of the name's bigrams that a document must contain
DIGITS = "零一二三四五六七八九"
EDITION = re.compile(r"第\s*([0-9０-９]+|[零〇一二三四五六七八九十百]+)\s*屆")


def numeral(text: str) -> int | None:
    """第N屆 as a number: Arabic or full-width digits, or Chinese numerals up to 999."""
    text = text.translate(str.maketrans("０１２３４５６７８９〇", "0123456789零"))
    if text.isdigit():
        return int(text)
    total, digit = 0, None
    for ch in text:
        if ch in DIGITS:
            digit = DIGITS.index(ch)
        elif ch in "十百":
            total += (digit if digit is not None else 1) * (10 if ch == "十" else 100)
            digit = None
        else:
            return None
    return total + (digit or 0)


def hints(cand) -> dict:
    """The contest's name, its 屆 number and the years its edition may carry."""
    title = cand["title"]
    years = set()
    if cand.get("record") and (CONTESTS / f"{cand['record']}.json").exists():
        rec = json.loads((CONTESTS / f"{cand['record']}.json").read_text(encoding="utf-8"))
        title = rec["title"]
        years.add(int(rec["id"][:4]))
    m = EDITION.search(title) or EDITION.search(cand["title"])
    years |= {int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", title)}
    years |= {int(y) + 1911 for y in re.findall(r"(?<!\d)(1\d\d)\s*(?:學年度|年度|年)", title)}
    if cand.get("deadline"):
        years.add(int(cand["deadline"][:4]))
    if not years:  # a school year spans two calendar years
        years = {int(TODAY[:4]), int(TODAY[:4]) + 1}
    return {"title": title, "edition": numeral(m.group(1)) if m else None, "years": sorted(years)}


def names_contest(h, text: str) -> str | None:
    """None when the text names the contest and its edition, else why not."""
    core = title_core(h["title"])
    if not text or not core or len(core & bigrams(text)) < NAME_SHARE * len(core):
        return "does not name the contest"
    if h["edition"] is not None:  # the first 第N屆 is the document's own; later ones may list past editions
        first = EDITION.search(text)
        if not first or numeral(first.group(1)) != h["edition"]:
            return f"not the {h['edition']}th edition"
        return None
    for y in h["years"]:
        if re.search(rf"(?<!\d){y}(?!\d)", text) or re.search(rf"(?<!\d){y - 1911}\s*(學年度|年度|年)", text):
            return None
    return "names no year of this edition"


def write_task(folder: Path, cand):
    h = hints(cand)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    known = [u["url"] for u in cand["urls"]]
    lines = ["# Task", "", f"Today: {TODAY}", f"Contest: {h['title']}"]
    if h["title"] != cand["title"]:
        lines.append(f"Also announced as: {cand['title']}")
    if h["edition"] is not None:
        lines.append(f"Edition: 第{h['edition']}屆")
    lines.append("Years this edition may carry: " + ", ".join(f"{y} (民國 {y - 1911})" for y in h["years"]))
    if cand.get("deadline"):
        lines.append(f"Deadline given in an announcement: {cand['deadline']}")
    lines += ["", "## Links already known (do not list them again)", ""] + [f"- {u}" for u in known]
    (folder / "task.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.copy(PIPELINE / "search.md", folder / "brief.md")
    shutil.copy(PIPELINE / "check_out.py", folder / "check.py")
    task = {"kind": "search", "key": cand["key"], "known": known}
    (folder / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def public(url: str) -> bool:
    """False for a host that is local or private (the script must not fetch such a link)."""
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:  # a malformed [host]
        return False
    if not host or "." not in host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[0-9a-fx.]+", host):
            return True
        try:  # 127.1, 0x7f.0.0.1 and other spellings of an IPv4 address
            ip = ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return True
    return ip.is_global


def problems(out, task) -> list:
    """What is wrong with a search out.json (empty: it may be applied)."""
    if not isinstance(out, dict) or not isinstance(out.get("urls"), list):
        return ['out.json must be {"urls": [...]}']
    urls = out["urls"]
    errs = []
    if len(urls) > MAX_URLS:
        errs.append(f"at most {MAX_URLS} links")
    known = {cq.same_url(u) for u in task["known"]}
    for u in urls:
        if not isinstance(u, str) or not re.match(r"https?://\S+$", u):
            errs.append(f"not a link: {u!r:.80}")
        elif not public(u):
            errs.append(f"not a public address: {u}")
        elif cq.same_url(u) in known:
            errs.append(f"already known: {u}")
        elif any(bad in u for bad in NOT_DOCS):
            errs.append(f"a form or a social media page holds no rules: {u}")
    return errs


def finish(folder: Path, cand) -> str:
    """Apply one search folder to its candidate (changed in place). Returns a line for the log."""
    task = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    try:
        out = json.loads((folder / "out.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "not run"
    except (OSError, json.JSONDecodeError) as e:
        return f"not applied: out.json is not valid JSON ({str(e)[:60]})"
    errs = problems(out, task)
    if errs:
        return f"not applied: {errs[0]}"
    h = hints(cand)
    kept, dropped = [], []
    for url in dict.fromkeys(out["urls"]):
        got, err = get(url)
        why = err or names_contest(h, got[0])
        if why:
            dropped.append(f"{url}: {why}")
        else:
            kept.append(url)
            cand["urls"].append({"url": url, "role": "rules", "name": ""})
    cand["searched"] = TODAY
    after = cand.pop("after_search", "given_up")
    if cand["status"] != "search":  # moved on in this round (triage added a link): leave it there
        pass
    elif kept:
        cand.update(status="new", attempts=0, note=f"search found {len(kept)} documents")
    else:
        cand.update(status=after, note="search found nothing that names this contest and edition")
    return f"{len(kept)} kept, {len(dropped)} dropped" + (f" ({dropped[0][:100]})" if dropped else "")
