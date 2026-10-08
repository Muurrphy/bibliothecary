"""Getting article text: a text/markdown file, or a web page (the article only).

Web pages go through trafilatura (Apache-2.0), which finds the article and leaves
out menus, related links and footers. Without it, a simple paragraph parser is used,
which keeps more of the page around the article."""

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


def _clean_title(title: str) -> str:
    return html.unescape(title or "").split("|")[0].split(" - ")[0].strip()


def from_html(markup: str) -> tuple[str, str]:
    try:
        import trafilatura
    except ImportError:
        trafilatura = None
    if trafilatura is not None:
        text = trafilatura.extract(markup, include_comments=False, include_tables=False, favor_precision=True)
        if text and len(text.split()) >= 80:
            meta = trafilatura.extract_metadata(markup)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = _clean_title(meta.title if meta and meta.title else "")
            if lines and lines[0] == title:
                lines = lines[1:]                       # the page title repeated as the first heading
            return title or "Untitled", "\n\n".join(lines)
    parser = _Paragraphs()
    parser.feed(markup)
    return _clean_title(parser.title) or "Untitled", "\n\n".join(parser.paragraphs)


MAX_WORDS = 12000          # a long paper is cut here (after dropping its references)
_LINE_END = re.compile(r"[.!?。！？:：]$")
_REFERENCES = re.compile(r"^\s*(\d+\.?\s*)?(references|bibliography|works cited|参考文献)\s*$", re.IGNORECASE)


def from_pdf(data: bytes) -> tuple[str, str]:
    """Text from a PDF, with lines joined back into paragraphs and the reference list left out."""
    import io

    import logging

    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)      # odd fonts are common and harmless here

    reader = PdfReader(io.BytesIO(data))
    lines = [line.strip() for page in reader.pages for line in (page.extract_text() or "").splitlines()]
    lines = [line for line in lines if line and not line.isdigit()]          # page numbers
    for i in range(len(lines) - 1, int(len(lines) * 0.5), -1):
        if _REFERENCES.match(lines[i]):
            lines = lines[:i]
            break
    width = sorted(len(line) for line in lines)[len(lines) * 3 // 4] if lines else 0
    paragraphs, buf = [], ""
    for line in lines:
        if buf.endswith("-") and line[:1].islower():
            buf = buf[:-1] + line                                              # hyphen-
        else:
            buf = f"{buf} {line}".strip()
        if _LINE_END.search(line) and len(line) < width * 0.8:                 # a short line ends a paragraph
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)
    meta = (reader.metadata.title if reader.metadata else None) or ""
    title = meta.strip() or (paragraphs[0][:120] if paragraphs else "Untitled")
    return title, _cap("\n\n".join(paragraphs))


def _cap(text: str) -> str:
    words = text.split(" ")
    return text if len(words) <= MAX_WORDS else " ".join(words[:MAX_WORDS]).rsplit("\n\n", 1)[0]


def load_article(where: str) -> tuple[str, str, str]:
    """(title, text, source) from a URL or a local .txt/.md/.html/.pdf file."""

    if re.match(r"https?://", where):
        req = urllib.request.Request(where, headers={"User-Agent": "Mozilla/5.0 (Margin reader)"})
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
            kind = res.headers.get_content_type()
            charset = res.headers.get_content_charset() or "utf-8"
        if kind == "application/pdf" or raw[:5] == b"%PDF-":
            title, text = from_pdf(raw)
        else:
            title, text = from_html(raw.decode(charset, "replace"))
        return title, _cap(text), where
    path = Path(where)
    if path.suffix.lower() == ".pdf":
        title, text = from_pdf(path.read_bytes())
        return title, text, path.name
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        title, text = from_html(raw)
        return title, text, path.name
    lines = raw.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).strip(), path.name
    return path.stem.replace("-", " ").replace("_", " ").title(), raw.strip(), path.name
