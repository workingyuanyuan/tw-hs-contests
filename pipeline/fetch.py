"""Fetch a document, store its extracted text and links in cache/, and record it in cache/index.json.

Run: uv run -q --isolated --with pymupdf --with playwright python -I pipeline/fetch.py <url> [<url> ...]

Handles HTML, plain text, PDF, Word (.docx), PowerPoint (.pptx), Google Docs, Sheets and
Slides (exported as text), Google Drive files (downloaded) and Google Drive folders (the
list of files). A page whose content is drawn by JavaScript is rendered in headless
Chromium. Images, and PDFs that hold only scanned pages, give no text: the entry says so.

The cache is keyed by the URL a reader clicks, not by the export or download address,
so evidence in a record links to the document as people see it.

Files per document: cache/<sha256>.txt (the text) and cache/<sha256>.links.json (the links
it contains, [{text, url}]). <sha256> is the hash of the text (of the bytes when there
is no text), so a changed document gets a new file and the old record's quotes can be
compared with it.
"""
import glob
import os
import hashlib
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
TAIPEI = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
SKIP = {"script", "style", "noscript", "template", "svg", "head"}
BLOCK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "section", "article", "table"}
# Hosts that send an empty shell or refuse a plain request; they are rendered in a browser.
BROWSER_HOSTS: set = set()
# bhuntr.com: the page is drawn by JavaScript, but the full rules are in the JSON-LD Event.
MIN_TEXT = 200  # an HTML page with less text than this is rendered in a browser


class FetchError(Exception):
    pass


class Html(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.skip = base, [], 0
        self.links, self._href, self._anchor = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
            return
        if tag in BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                self._href, self._anchor = urljoin(self.base, href.strip()), []
        if tag == "img" and self._href is not None:
            alt = dict(attrs).get("alt")
            if alt:
                self._anchor.append(alt)

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        if tag == "a" and self._href is not None:
            self.links.append({"text": " ".join("".join(self._anchor).split()), "url": self._href})
            self._href = None

    def handle_data(self, data):
        if self.skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data)


def tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "")
    text = re.sub(r"[ \t 　]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def decode(body: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I) or re.search(rb'charset=["\']?([\w-]+)', body[:4096], re.I)
    charset = m.group(1) if m else "utf-8"
    charset = charset.decode("ascii") if isinstance(charset, bytes) else charset
    if charset.lower() in {"big5", "big5-hkscs"}:
        charset = "cp950"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def unwrap(url: str) -> str:
    """The target of a redirect link (bhuntr external-link, Google and Facebook redirects)."""
    u = urlparse(url)
    if re.search(r"external-link|/url$|/l\.php$|redirect", u.path):
        for key in ("url", "q", "u", "target"):
            target = parse_qs(u.query).get(key)
            if target and target[0].startswith("http"):
                return target[0]
    return url


def unique_links(links):
    seen, out = set(), []
    for link in links:
        link = {**link, "url": unwrap(link["url"])}
        if link["url"] not in seen:
            seen.add(link["url"])
            out.append(link)
    return out


def from_html(html: str, base: str):
    parser = Html(base)
    parser.feed(html)
    return tidy("".join(parser.parts)), unique_links(parser.links)


def from_pdf(body: bytes):
    import pymupdf  # noqa: PLC0415

    doc = pymupdf.open(stream=body, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    links = [{"text": "", "url": l["uri"]} for page in doc for l in page.get_links() if l.get("uri")]
    return tidy(text), unique_links(links), {"pages": doc.page_count}


def from_office(body: bytes):
    """Text of a .docx or .pptx: the w:t / a:t runs, one paragraph per line."""
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        if "word/document.xml" in names:
            parts = ["word/document.xml"]
            kind = "docx"
        else:
            parts = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                           key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
            kind = "pptx"
        if not parts:
            raise FetchError("zip file that is neither .docx nor .pptx")
        lines = []
        for name in parts:
            xml = z.read(name).decode("utf-8", errors="replace")
            for para in re.findall(r"<(?:w|a):p[ >].*?</(?:w|a):p>", xml, re.S):
                runs = re.findall(r"<(?:w|a):t(?: [^>]*)?>([^<]*)</(?:w|a):t>", para)
                if runs:
                    lines.append("".join(runs))
        text = "\n".join(lines)
        for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
            text = text.replace(a, b)
    return tidy(text), [], {"kind": kind}


def drive_folder(html: str, url: str):
    """The files listed in a public Google Drive folder, as links."""
    links = []
    for m in re.finditer(r'<tr[^>]*data-id="([A-Za-z0-9_-]{20,})"[^>]*>(.*?)</tr>', html, re.S):
        name = " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split())
        name = re.split(r"\s(?:擁有者|Owner|上次修改|Last modified)", name)[0][:120]
        links.append({"text": name, "url": f"https://drive.google.com/file/d/{m.group(1)}/view"})
    text = "Google 雲端硬碟資料夾，內含檔案：\n" + "\n".join(f"- {l['text']}" for l in links)
    return text, links


def bhuntr(html: str, url: str):
    """Text of a bhuntr.com contest page from its JSON-LD Event; links from the HTML."""
    import html as htmllib  # noqa: PLC0415

    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in data.get("@graph", [data]) if isinstance(data, dict) else data:
            if isinstance(item, dict) and item.get("@type") == "Event" and item.get("description"):
                desc = item["description"].replace("&nbsp;", "\n")
                desc = htmllib.unescape(re.sub(r"<[^>]+>", "\n", desc))
                # startDate and endDate are not the contest's dates (endDate is the time of the request).
                try:  # the attachment links are drawn by JavaScript
                    _, links = browser_text(url)
                except Exception:  # noqa: BLE001
                    _, links = from_html(html, url)
                return tidy(item.get("name", "") + "\n" + desc), links
    return None


def source_of(url: str):
    """(address to download, how to read it) for a URL a reader clicks."""
    u = urlparse(url)
    m = re.match(r"/(document|spreadsheets|presentation)/d/([A-Za-z0-9_-]+)", u.path)
    if u.netloc == "docs.google.com" and m:
        fmt = {"document": "txt", "spreadsheets": "csv", "presentation": "txt"}[m.group(1)]
        return f"https://docs.google.com/{m.group(1)}/d/{m.group(2)}/export?format={fmt}", "export"
    if u.netloc == "drive.google.com":
        m = re.match(r"/file/d/([A-Za-z0-9_-]+)", u.path)
        file_id = m.group(1) if m else (parse_qs(u.query).get("id") or [None])[0]
        if "/folders/" in u.path:
            return url, "folder"
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}", "download"
    return url, "auto"


def http_get(url: str):
    # Links on school sites often hold spaces and Chinese characters unescaped.
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.read(), resp.headers.get("Content-Type", ""), resp.status
    except urllib.error.HTTPError as e:
        return e.read(), e.headers.get("Content-Type", ""), e.code


def chromium() -> str | None:
    """A Chromium to drive: $CHROME_PATH, else Playwright's own headless shell, else Playwright's default."""
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    exe = sorted(glob.glob(str(Path.home() / ".cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell")))
    return exe[-1] if exe else None


def browser_text(url: str, scrolls: int = 0):
    """Render a page in headless Chromium and return (text, links). `scrolls`: times at most to scroll
    to the bottom first, for lists that load more items as the reader scrolls; it stops early when the
    page stops growing.

    The page is loaded, then given up to 20 s to fall network-idle: pages that keep a connection open
    (Wix, chat widgets) never do, and are read after the wait. A link with no text of its own (an image
    link) takes the text of another link to the same address, else its title, aria-label or image alt."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    exe = chromium()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(user_agent=UA, locale="zh-TW", ignore_https_errors=True)
        resp = page.goto(url, wait_until="load", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeout:
            page.wait_for_timeout(3000)
        page.wait_for_timeout(1500)
        height = page.evaluate("document.body.scrollHeight")
        for _ in range(scrolls):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            grown = page.evaluate("document.body.scrollHeight")
            for _ in range(3):  # nothing loaded yet: wait a little longer before calling it the end
                if grown != height:
                    break
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                grown = page.evaluate("document.body.scrollHeight")
            if grown == height:
                break
            height = grown
        text = page.evaluate("document.body.innerText")
        links = page.evaluate("""(() => {
            const as = [...document.querySelectorAll('a[href]')];
            const named = {};
            for (const a of as) { const t = a.innerText.trim(); if (t && !(a.href in named)) named[a.href] = t; }
            return as.map(a => {
                const img = a.querySelector('img[alt]');
                const t = a.innerText.trim() || named[a.href] || a.title || a.getAttribute('aria-label') || (img ? img.alt : '');
                return {text: t.replace(/\\s+/g, ' '), url: a.href};
            }).filter(l => /^https?:/.test(l.url));
        })()""")
        status = resp.status if resp else 0
        browser.close()
    if status >= 400:
        raise FetchError(f"HTTP {status} in the browser")
    return tidy(text), unique_links(links)


def read(url: str):
    """Return (bytes for the hash, text, links, info)."""
    target, how = source_of(url)
    host = urlparse(url).netloc
    if host in BROWSER_HOSTS:
        text, links = browser_text(url)
        return text.encode("utf-8"), text, links, {"kind": "html-rendered"}
    body, ctype, status = http_get(target)
    if how == "download" and b"<html" in body[:2000].lower():
        # Drive asks to confirm the download of a file it cannot scan.
        m = re.search(rb'name="confirm" value="([^"]+)"', body) or re.search(rb"confirm=([0-9A-Za-z_-]+)", body)
        uuid = re.search(rb'name="uuid" value="([^"]+)"', body)
        if m:
            extra = f"&confirm={m.group(1).decode()}" + (f"&uuid={uuid.group(1).decode()}" if uuid else "")
            body, ctype, status = http_get(f"https://drive.usercontent.google.com/download?id={parse_qs(urlparse(target).query)['id'][0]}&export=download{extra}")
    if status >= 400 and how == "auto" and "html" in ctype:
        try:
            text, links = browser_text(url)
        except Exception as e:  # noqa: BLE001  keep the status the server gave
            raise FetchError(f"HTTP {status}; the browser failed too: {type(e).__name__}") from e
        return text.encode("utf-8"), text, links, {"kind": "html-rendered"}
    if status >= 400:
        raise FetchError(f"HTTP {status}")
    if body[:5] == b"%PDF-":
        text, links, info = from_pdf(body)
        return body, text, links, {"kind": "pdf", **info}
    if body[:2] == b"PK":
        text, links, info = from_office(body)
        return body, text, links, info
    if body[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"GIF8") or ctype.startswith("image/"):
        return body, "", [], {"kind": "image"}
    if body[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return body, "", [], {"kind": "old-office"}
    html = decode(body, ctype)
    if how == "folder":
        text, links = drive_folder(html, url)
        return body, text, links, {"kind": "drive-folder"}
    if host.endswith("bhuntr.com"):
        found = bhuntr(html, url)
        if found:
            return body, found[0], found[1], {"kind": "html-jsonld"}
    if "html" in ctype or "<html" in html[:3000].lower():
        text, links = from_html(html, url)
        if len(text) < MIN_TEXT and how == "auto":
            text, links = browser_text(url)
            return text.encode("utf-8"), text, links, {"kind": "html-rendered"}
        return body, text, links, {"kind": "html"}
    return body, tidy(html), [], {"kind": "text"}


def load_index() -> dict:
    path = CACHE / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# Lines that change while the document does not: view counters, countdowns, relative times.
NOISE = re.compile(r"(瀏覽|點閱|點擊|人次|人數|觀看|閱讀數|[Vv]iews?|[Hh]its?)\D{0,6}[:：]?\s*[\d,]+"
                   r"|^[\d,.\s]{1,12}$|報名期限\s*[\d.]+\s*天|閱讀\s*\d+\s*分鐘"
                   r"|昨天|前天|今天|剛剛|\d+\s*(秒|分鐘|小時|天)前"
                   r"|IP\s*(位置|位址|地址)?\s*[:：]\s*\d{1,3}(\.\d{1,3}){3}")  # the visitor's IP address, shown by some pages
# A change that can touch a fact of the record: a deadline, a date, registration, a postponement,
# a fee, a correction, a cancellation.
FACT_WORDS = re.compile(r"截止|延期|延長|展延|延後|提前|報名|收件|繳交|期限|日期|報名費|參賽費|費用|收費|保證金|額滿"
                        r"|更正|修正|勘誤|異動|補充|取消|停辦|\d{1,2}\s*月\s*\d{1,2}\s*日"
                        r"|\d{2,4}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{1,2}")


def meaningful_lines(text: str) -> list:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip() and not NOISE.search(line)]


def fingerprint(text: str) -> str:
    """Hash of the text without noise lines and whitespace: what decides that a document changed."""
    return hashlib.sha256("\n".join(meaningful_lines(text)).encode("utf-8")).hexdigest()


def fetch(url: str) -> dict:
    return store(url, *read(url))


def store(url: str, body: bytes, text: str, links: list, info: dict) -> dict:
    """Write a document read by read() to the cache and the index; returns its index entry."""
    # The hash of the text, so that a page whose markup changes on every request (a clock, a
    # token) keeps its hash; a document with no text is hashed by its bytes.
    sha = hashlib.sha256(text.encode("utf-8") if text else body).hexdigest()
    CACHE.mkdir(exist_ok=True)
    (CACHE / f"{sha}.txt").write_text(text, encoding="utf-8")
    (CACHE / f"{sha}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    index = load_index()
    previous = index.get(url, {}).get("sha256")
    index[url] = {
        "sha256": sha,
        "fetched_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(text) if text else sha,
        "chars": len(text),
        "links": len(links),
        **info,
    }
    if previous and previous != sha:
        index[url]["previous_sha256"] = previous
    tmp = (CACHE / "index.json").with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CACHE / "index.json")
    return index[url]


def cached(url: str):
    """(text, links) of a cached document, or None."""
    entry = load_index().get(url)
    if not entry:
        return None
    base = CACHE / entry["sha256"]
    links_path = Path(f"{base}.links.json")
    links = json.loads(links_path.read_text(encoding="utf-8")) if links_path.exists() else []
    return Path(f"{base}.txt").read_text(encoding="utf-8"), unique_links(links)


if __name__ == "__main__":
    failed = 0
    for u in sys.argv[1:]:
        try:
            print(u, json.dumps(fetch(u), ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(u, "FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(1 if failed else 0)
