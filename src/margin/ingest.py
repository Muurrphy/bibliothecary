"""Getting article text: a text/markdown file, or a web page (paragraphs only)."""

from __future__ import annotations

import html
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


class _Paragraphs(HTMLParser):
    KEEP = {"p", "h1", "h2", "h3", "li", "blockquote"}
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "figure"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self.paragraphs = "", []
        self._buf: list[str] | None = None
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.KEEP and not self._skip:
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.KEEP and self._buf is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(text) > 40 or (tag.startswith("h") and text):
                self.paragraphs.append(text)
            self._buf = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._buf is not None and not self._skip:
            self._buf.append(data)


def from_html(markup: str) -> tuple[str, str]:
    parser = _Paragraphs()
    parser.feed(markup)
    title = html.unescape(parser.title).split("|")[0].split(" - ")[0].strip()
    return title or "Untitled", "\n\n".join(parser.paragraphs)


def load_article(where: str) -> tuple[str, str, str]:
    """(title, text, source) from a URL or a local .txt/.md/.html file."""

    if re.match(r"https?://", where):
        req = urllib.request.Request(where, headers={"User-Agent": "Mozilla/5.0 (Margin reader)"})
        with urllib.request.urlopen(req, timeout=30) as res:
            markup = res.read().decode(res.headers.get_content_charset() or "utf-8", "replace")
        title, text = from_html(markup)
        return title, text, where
    path = Path(where)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        title, text = from_html(raw)
        return title, text, path.name
    lines = raw.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).strip(), path.name
    return path.stem.replace("-", " ").replace("_", " ").title(), raw.strip(), path.name
