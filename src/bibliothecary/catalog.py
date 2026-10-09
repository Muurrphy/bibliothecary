"""The library's own books: a short list of public-domain books the librarian can fetch for you.

    entries()                       the list (catalog.toml, plus ~/Bibliothecary/catalog.toml)
    get(client, "darwin-emotions")  fetch it from its source and put it on the shelf

Only three sources are used (see catalog.toml): Standard Ebooks, Project Gutenberg and Wikisource.
The file is fetched once, from your own computer, into ~/Bibliothecary/inbox/, and shelved like a
book you sent yourself. A sample book is included, so the books feature works without fetching.
"""

from __future__ import annotations

import json
import re
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import bookfile, books, library

DEFAULT = Path(__file__).with_name("catalog.toml")
SAMPLE = Path(__file__).parent / "samples" / "seneca-on-the-shortness-of-life.epub"
SOURCES = ("standardebooks", "gutenberg", "wikisource")
SHELVES = {"life": ("生命与心智", "Life and mind"), "civilization": ("文明与散文", "Civilization and essays")}
AGENT = "Bibliothecary/0.4 (personal reading app; +https://github.com/Muurrphy/bibliothecary)"


def entries() -> list[dict[str, Any]]:
    found = {b["id"]: b for b in tomllib.loads(DEFAULT.read_text(encoding="utf-8"))["book"]}
    mine = library.home() / "catalog.toml"
    if mine.is_file():
        for b in tomllib.loads(mine.read_text(encoding="utf-8")).get("book", []):
            if b.get("id"):
                found[b["id"]] = {**found.get(b["id"], {}), **b}
    return [b for b in found.values() if b.get("source") in SOURCES and b.get("ref")]


def find(query: str) -> dict[str, Any] | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    for b in entries():
        if q == b["id"]:
            return b
    return next((b for b in entries() if q in b["id"] or q in b["title"].lower() or q in b.get("title_zh", "")
                 or q in b.get("author", "").lower()), None)


def listing(chinese: bool) -> str:
    lines = []
    for shelf, names in SHELVES.items():
        lines.append(("【" + names[0] + "】") if chinese else f"[{names[1]}]")
        for b in entries():
            if b.get("shelf") == shelf:
                name = b.get("title_zh") if chinese and b.get("title_zh") else b["title"]
                author = b.get("author", "")
                lines.append(f"· {b['id']} — {name}（{author}，{b.get('year', '')}）" if chinese
                             else f"· {b['id']} — {name} ({author}, {b.get('year', '')})")
        lines.append("")
    return "\n".join(lines).strip()


def _open(url: str, timeout: float = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read(), res.headers.get_content_type()


def source_url(book: dict[str, Any]) -> str:
    """Where the book's page is, for people (and for the shelf's record)."""
    ref = book["ref"]
    if book["source"] == "standardebooks":
        return f"https://standardebooks.org/ebooks/{ref}"
    if book["source"] == "gutenberg":
        return f"https://www.gutenberg.org/ebooks/{ref}"
    return f"https://zh.wikisource.org/wiki/{urllib.parse.quote(ref)}"


def _wikisource(book: dict[str, Any], folder: Path) -> Path:
    """One Wikisource page (or each page its contents list links to), assembled into a small EPUB."""
    api = "https://zh.wikisource.org/w/api.php?"

    def page(title: str) -> dict:
        data, _ = _open(api + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text|links",
                                                     "redirects": 1, "format": "json", "formatversion": 2}))
        return json.loads(data).get("parse") or {}

    first = page(book["ref"])
    chapters = bookfile.chapters_from_html(first.get("text", ""))
    if not chapters:                                   # a contents page: fetch the pages it lists
        for link in first.get("links", []):
            title = link.get("title", "")
            if title.startswith(book["ref"] + "/"):
                found = bookfile.chapters_from_html(page(title).get("text", ""), level="h1")
                paragraphs = [p for c in found for p in ([c.title] if c.title else []) + c.paragraphs]
                if paragraphs:
                    chapters.append(bookfile.Chapter(title.split("/", 1)[1], paragraphs))
    if not chapters:
        raise ValueError(f"found no text on Wikisource for {book['ref']}")
    parsed = bookfile.Parsed(book["title"], book.get("author", ""), book.get("language", "zh"), chapters)
    return bookfile.write_epub(folder / f"{book['id']}.epub", parsed, source=source_url(book),
                               rights="Public domain. Text from Wikisource.")


def fetch(book: dict[str, Any], folder: Path | None = None) -> Path:
    """Download the book file into the inbox and return its path."""
    folder = folder or library.home() / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    if book["source"] == "wikisource":
        return _wikisource(book, folder)
    if book["source"] == "standardebooks":
        page, _ = _open(source_url(book))
        links = [h for h in re.findall(r'href="([^"]+\.epub)"', page.decode("utf-8", "replace"))
                 if "kepub" not in h and "advanced" not in h]
        if not links:
            raise ValueError(f"Standard Ebooks has no download for {book['ref']} yet")
        url = urllib.parse.urljoin("https://standardebooks.org/", links[0]) + "?source=download"
    else:
        url = f"https://www.gutenberg.org/ebooks/{book['ref']}.epub3.images"
    data, kind = _open(url, timeout=120)
    if not data.startswith(b"PK"):
        raise ValueError(f"{url} did not return an EPUB ({kind})")
    path = folder / f"{book['id']}.epub"
    path.write_bytes(data)
    return path


def get(client, query: str, *, explain: str = "English", log=None) -> books.Book:
    """Fetch a catalog book (or find it on the shelf already) and shelve it. "sample" is the bundled one."""
    if (query or "").strip().lower() in ("sample", "示例", "样书"):
        return sample(explain=explain, log=log)
    book = find(query)
    if book is None:
        raise ValueError(f"no book “{query}” in the catalog")
    for shelved in books.shelf():
        if shelved.data.get("catalog") == book["id"]:
            return shelved
    if log:
        log(f"fetching “{book['title']}” from {book['source']}…")
    path = fetch(book)
    return _shelve(client, path, book, explain=explain, log=log)


def _shelve(client, path: Path, book: dict[str, Any], *, explain: str, log=None) -> books.Book:
    title = book.get("title_zh") if books.is_chinese(explain) and book.get("title_zh") else book["title"]
    shelved = books.add(path, client=None, title=title, mode=book.get("mode"), explain=explain, log=log)
    shelved.data.update(catalog=book["id"], source=source_url(book), author=book.get("author") or shelved.data.get("author"),
                        kind=shelved.data.get("kind") or ("nonfiction" if book.get("mode") == "digest" else "essays"),
                        why=book.get("why_zh") if books.is_chinese(explain) else book.get("why", ""))
    if book.get("language"):
        shelved.data["language"] = book["language"]
    shelved.save()
    return shelved


def sample(*, explain: str = "English", log=None) -> books.Book:
    """The sample book that comes with the project: Seneca, On the Shortness of Life."""
    for shelved in books.shelf():
        if shelved.data.get("catalog") == "sample-seneca":
            return shelved
    entry = {"id": "sample-seneca", "title": "On the Shortness of Life", "title_zh": "论生命之短暂",
             "author": "Seneca", "source": "standardebooks", "ref": "seneca/dialogues/aubrey-stewart", "mode": "text",
             "why": "Seneca's letter on how time is lost (Aubrey Stewart's translation, 1900). About 8,000 words.",
             "why_zh": "塞涅卡谈时间怎样被浪费（Aubrey Stewart 1900 年英译本），约八千词。"}
    return _shelve(None, SAMPLE, entry, explain=explain, log=log)
