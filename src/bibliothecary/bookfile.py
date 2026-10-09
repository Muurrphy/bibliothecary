"""Reading a whole book file into chapters: EPUB, TXT or PDF.

    parse("Darwin.epub") -> Parsed(title, author, language, chapters=[Chapter(title, paragraphs), ...])

EPUB is a zip of XHTML files, so it is read here with the standard library (no EbookLib, which is
AGPL). The chapters follow the book's own table of contents; front matter, lists of contents and
indexes, and Project Gutenberg's header and licence are left out. TXT files are cut at chapter
headings ("第三章", "Chapter 3", or short title lines standing alone). PDF files use their bookmarks,
then headings in the text, and otherwise even parts.
"""

from __future__ import annotations

import html
import posixpath
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

BOOK_TYPES = (".epub", ".txt", ".pdf")


@dataclass
class Chapter:
    title: str
    paragraphs: list[str]

    @property
    def size(self) -> int:
        """Characters, which is the fair measure for Chinese; English words are about 6 characters."""
        return sum(len(p) for p in self.paragraphs)


@dataclass
class Parsed:
    title: str
    author: str = ""
    language: str = ""
    chapters: list[Chapter] = field(default_factory=list)


# ---- shared -------------------------------------------------------------------------------
_SKIP_TITLES = re.compile(
    r"^\W*(detailed |table of )?contents\W*$|^\W*(list of )?(illustrations|plates|figures)\W*$|^\W*(general )?index\W*$|"
    r"^\W*(foot|end)?notes\W*$|^\W*(bibliography|references)\W*$|^\s*目\s*[录錄]\s*$|^\s*索\s*引\s*$|^\s*(注释|参考文献)\s*$|"
    r"^\s*(the )?full project gutenberg license|^\W*copyright( page)?\W*$|^\s*版权(信息|页)?\s*$|^\W*cover\W*$|^\s*封面\s*$",
    re.IGNORECASE)
_PG_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG", re.IGNORECASE)
_PG_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.IGNORECASE)
MIN_CHAPTER = 300            # characters; shorter pieces (title pages, epigraphs) join the next chapter


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _tidy(chapters: list[Chapter]) -> list[Chapter]:
    """Drop the Gutenberg wrapper, contents pages and indexes; fold tiny pieces into their neighbour."""
    flat = [(c.title, p) for c in chapters for p in c.paragraphs]
    start = next((i for i, (_, p) in enumerate(flat) if _PG_START.search(p)), None)
    end = next((i for i, (_, p) in enumerate(flat) if _PG_END.search(p)), None)
    out: list[Chapter] = []
    i = 0
    for chapter in chapters:
        keep = []
        for p in chapter.paragraphs:
            inside = (start is None or i > start) and (end is None or i < end)
            if inside and p and not re.match(r"^(\*\*\*|produced by|e-?text prepared by)", p, re.IGNORECASE):
                keep.append(p)
            i += 1
        title = chapter.title.lower()
        while keep and len(keep[0]) <= 80 and keep[0].lower().strip(" .") in title:
            keep.pop(0)                                       # the heading again, already the chapter's title
        if keep and not _SKIP_TITLES.search(chapter.title):
            out.append(Chapter(chapter.title, keep))
    sizes = sorted(c.size for c in out)
    typical = sizes[len(sizes) * 3 // 4] if sizes else 0
    while len(out) > 2 and out[0].size < typical * 0.1:      # title pages, "works by", contents at the front
        out.pop(0)
    merged: list[Chapter] = []
    carry: Chapter | None = None
    for chapter in out:
        if carry is not None:
            chapter = Chapter(chapter.title, carry.paragraphs + chapter.paragraphs)
            carry = None
        if chapter.size < MIN_CHAPTER:
            carry = chapter
            continue
        merged.append(chapter)
    if carry is not None and merged:
        merged[-1].paragraphs += carry.paragraphs
    elif carry is not None:
        merged.append(carry)
    return merged


# ---- EPUB ---------------------------------------------------------------------------------
class _Blocks(HTMLParser):
    """Paragraph texts of one XHTML file, and at which paragraph each element id appears."""

    BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "dd", "dt", "td", "div",
             "section", "article", "tr", "br"}
    SKIP = {"script", "style", "head", "title", "nav"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.headings: list[int] = []            # indexes of paragraphs that were headings
        self.ids: dict[str, int] = {}
        self._buf: list[str] = []
        self._skip = 0
        self._heading = False

    def _flush(self) -> None:
        text = _clean("".join(self._buf))
        self._buf = []
        if text:
            if self._heading:
                self.headings.append(len(self.paragraphs))
            self.paragraphs.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
            return
        if tag in self.BLOCK:
            self._flush()
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = True
        for key, value in attrs:
            if key in ("id", "name") and value and value not in self.ids:
                self.ids[value] = len(self.paragraphs)
        if tag == "img":
            alt = dict(attrs).get("alt")
            if alt and len(alt) > 30:
                self._buf.append(f" [{alt}] ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in self.BLOCK or re.fullmatch(r"h[1-6]", tag):
            self._flush()
            if re.fullmatch(r"h[1-6]", tag):
                self._heading = False

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _xml(data: bytes) -> ElementTree.Element:
    return ElementTree.fromstring(data)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_all(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [e for e in root.iter() if _local(e.tag) == name]


Toc = list[tuple[int, str, str]]                    # (depth, title, file#anchor), in reading order


def _toc_epub3(z: zipfile.ZipFile, path: str) -> Toc:
    root = _xml(z.read(path))
    base = posixpath.dirname(path)

    def walk(ol: ElementTree.Element, depth: int, out: Toc) -> None:
        for li in [c for c in ol if _local(c.tag) == "li"]:
            a = next((c for c in li if _local(c.tag) in ("a", "span")), None)
            if a is not None and a.get("href"):
                out.append((depth, _clean("".join(a.itertext())),
                            posixpath.normpath(posixpath.join(base, unquote(a.get("href"))))))
            for sub in [c for c in li if _local(c.tag) == "ol"]:
                walk(sub, depth + 1, out)

    for nav in _find_all(root, "nav"):
        kind = next((v for k, v in nav.attrib.items() if _local(k) == "type"), "")
        if kind and kind != "toc":
            continue
        ol = next(iter(_find_all(nav, "ol")), None)
        out: Toc = []
        if ol is not None:
            walk(ol, 1, out)
        if out:
            return out
    return []


def _toc_ncx(z: zipfile.ZipFile, path: str) -> Toc:
    root = _xml(z.read(path))
    base = posixpath.dirname(path)
    nav_map = next(iter(_find_all(root, "navMap")), None)
    out: Toc = []

    def walk(parent: ElementTree.Element, depth: int) -> None:
        for point in [c for c in parent if _local(c.tag) == "navPoint"]:
            label = next(iter(_find_all(point, "text")), None)
            content = next((c for c in point if _local(c.tag) == "content"), None)
            if content is not None and content.get("src"):
                out.append((depth, _clean("".join(label.itertext())) if label is not None else "",
                            posixpath.normpath(posixpath.join(base, unquote(content.get("src"))))))
            walk(point, depth + 1)

    if nav_map is not None:
        walk(nav_map, 1)
    return out


def _sizes(starts: list[tuple[int, int, str]], flat: list[tuple[int, int, str]]) -> list[int]:
    sizes, j = [0] * len(starts), -1
    keys = [s[:2] for s in starts]
    for fi, pi, p in flat:
        while j + 1 < len(keys) and (fi, pi) >= keys[j + 1]:
            j += 1
        if j >= 0:
            sizes[j] += len(p)
    return sizes


def _choose_level(levels: dict[int, list[tuple[int, int, str]]], flat) -> list[tuple[int, int, str]]:
    """The shallowest contents level that reads like chapters: at least three real pieces, and pieces
    none bigger than a very long chapter (deeper levels are sections inside chapters)."""
    for depth in sorted(levels):
        real = sorted(s for s in _sizes(levels[depth], flat) if s >= 3000)
        if len(real) >= 3 and real[-1] <= 300_000:
            return levels[depth]
    return levels[max(levels)]


def parse_epub(path: str | Path) -> Parsed:
    with zipfile.ZipFile(path) as z:
        container = _xml(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in _find_all(container, "rootfile"))
        opf = _xml(z.read(opf_path))
        base = posixpath.dirname(opf_path)

        def meta(name: str) -> str:
            found = [e for e in _find_all(opf, name) if (e.text or "").strip()]
            return _clean(found[0].text) if found else ""

        manifest = {e.get("id"): e for e in _find_all(opf, "item")}
        spine = [manifest[r.get("idref")] for r in _find_all(opf, "itemref") if r.get("idref") in manifest]
        files = [posixpath.normpath(posixpath.join(base, unquote(item.get("href")))) for item in spine]

        toc: Toc = []
        nav = next((e for e in manifest.values() if "nav" in (e.get("properties") or "").split()), None)
        if nav is not None:
            toc = _toc_epub3(z, posixpath.normpath(posixpath.join(base, unquote(nav.get("href")))))
        if not toc:
            ncx = next((e for e in manifest.values() if e.get("media-type") == "application/x-dtbncx+xml"), None)
            if ncx is not None:
                toc = _toc_ncx(z, posixpath.normpath(posixpath.join(base, unquote(ncx.get("href")))))

        parsed: dict[str, _Blocks] = {}
        for name in files:
            blocks = _Blocks()
            try:
                blocks.feed(z.read(name).decode("utf-8", "replace"))
            except KeyError:
                continue
            blocks.close()
            parsed[name] = blocks

    flat: list[tuple[int, int, str]] = [(fi, pi, p) for fi, f in enumerate(files) if f in parsed
                                        for pi, p in enumerate(parsed[f].paragraphs)]
    # every place a chapter may start: (file index, paragraph index, title), per contents depth
    levels: dict[int, list[tuple[int, int, str]]] = {}
    deepest = max((d for d, _, _ in toc), default=0)
    for depth in range(1, min(deepest, 4) + 1):
        found = set()
        for d, title, target in toc:
            name, _, anchor = target.partition("#")
            if d > depth or name not in parsed:
                continue
            found.add((files.index(name), parsed[name].ids.get(anchor, 0) if anchor else 0, title))
        if found:
            levels[depth] = sorted(found)
    starts = _choose_level(levels, flat) if levels else []
    if not starts:                                   # no usable contents: one chapter per file
        starts = [(i, 0, (parsed[f].paragraphs[h[0]] if (h := parsed[f].headings) else f"Part {i + 1}"))
                  for i, f in enumerate(files) if f in parsed]
    chapters: list[Chapter] = []
    lead = [p for fi, pi, p in flat if (fi, pi) < starts[0][:2]]
    if lead:
        chapters.append(Chapter("", lead))
    for n, (fi, pi, title) in enumerate(starts):
        stop = starts[n + 1][:2] if n + 1 < len(starts) else (len(files), 0)
        chapters.append(Chapter(title or f"Part {n + 1}", [p for f, i, p in flat if (fi, pi) <= (f, i) < stop]))
    return Parsed(meta("title") or Path(path).stem, meta("creator"), meta("language"), _tidy(chapters))


# ---- TXT ----------------------------------------------------------------------------------
_NUM = r"[0-9０-９零〇一二三四五六七八九十百千两]+"
_HEADING = re.compile(
    rf"^\s*(第{_NUM}[章回节節卷篇部集讲講]|卷{_NUM}|(chapter|lecture|book|part|letter|essay)\s+([0-9]+|[ivxlcdm]+)\b(?!.*\d)|"
    r"(序|序言|自序|前言|引言|楔子|小引|后记|後記|尾声|尾聲|跋|目录|索引|注释|参考文献)\s*$|"
    r"(index|bibliography|references|notes|footnotes|contents)\W*$)", re.IGNORECASE)
_ROMAN = re.compile(r"^\s*[ivxlcdm]+\.\s*$", re.IGNORECASE)          # "IV." alone: a heading in plain text


def _read_text(path: str | Path) -> str:
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "big5", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _blocks_of_text(text: str) -> list[list[str]]:
    """Lines grouped by blank lines."""
    groups, buf = [], []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            buf.append(line.strip())
        elif buf:
            groups.append(buf)
            buf = []
    if buf:
        groups.append(buf)
    return groups


def _is_heading(line: str, roman: bool = False) -> bool:
    return len(line) <= 40 and bool(_HEADING.match(line) or (roman and _ROMAN.match(line)))


def split_text(text: str, title: str = "", *, roman: bool = True, standalone: bool = True) -> list[Chapter]:
    groups = _blocks_of_text(text)
    # one paragraph per line when the file does (Chinese TXT), else per blank-line block (wrapped English)
    lines = [line for g in groups for line in g]
    lines_per_group = len(lines) / max(1, len(groups))
    lengths = sorted(len(line) for line in lines) or [0]
    chinese = len(re.findall(r"[㐀-鿿]", text)) > len(text) * 0.2
    wrapped = not chinese and lines_per_group > 2 and 55 <= lengths[len(lengths) * 3 // 4] <= 85
    paragraphs: list[tuple[str, bool]] = []          # (text, standalone short line)
    for group in groups:
        lines = [" ".join(group)] if wrapped else group
        for line in lines:
            paragraphs.append((_clean(line), len(group) == 1))
    marked = [i for i, (p, _) in enumerate(paragraphs) if _is_heading(p, roman)]
    if len(marked) < 3:          # few "第X章": take short title lines standing alone (no end punctuation) too
        alone = [i for i, (p, single) in enumerate(paragraphs)
                 if single and len(p) <= 20 and not re.search(r"[。！？.!?，,:：；;”」』\"…—]$", p)]
        if standalone and len(alone) >= 3:
            marked = sorted(set(marked) | set(alone))
        if len(marked) < 2:
            marked = []
    chapters: list[Chapter] = []
    if not marked:
        return _even_parts([p for p, _ in paragraphs], title)
    if marked[0] > 0:
        chapters.append(Chapter("", [p for p, _ in paragraphs[:marked[0]]]))
    for n, i in enumerate(marked):
        end = marked[n + 1] if n + 1 < len(marked) else len(paragraphs)
        chapters.append(Chapter(paragraphs[i][0], [p for p, _ in paragraphs[i + 1:end]]))
    return chapters


def _even_parts(paragraphs: list[str], title: str, size: int = 20000) -> list[Chapter]:
    parts, buf, n = [], [], 0
    for p in paragraphs:
        buf.append(p)
        n += len(p)
        if n >= size:
            parts.append(Chapter(f"Part {len(parts) + 1}", buf))
            buf, n = [], 0
    if buf:
        parts.append(Chapter(f"Part {len(parts) + 1}", buf))
    return parts


def parse_txt(path: str | Path) -> Parsed:
    text = _read_text(path)
    title = Path(path).stem.replace("_", " ")
    return Parsed(title, "", "", _tidy(split_text(text, title)))


# ---- PDF ----------------------------------------------------------------------------------
_LINE_END = re.compile(r"[.!?。！？:：”\"]$")


def _pdf_lines(reader) -> list[tuple[int, str]]:
    raw = [(n, line.strip()) for n, page in enumerate(reader.pages)
           for line in (page.extract_text() or "").splitlines()]
    raw = [(n, line) for n, line in raw if line and not re.fullmatch(r"[\divxlcdm]+", line, re.IGNORECASE)]
    # running heads repeat on many pages; page numbers stuck to them too
    counts = Counter(re.sub(r"\d+", "", line).strip().lower() for _, line in raw if len(line) < 60)
    pages = max(1, len(reader.pages))
    return [(n, line) for n, line in raw
            if not (len(line) < 60 and counts[re.sub(r"\d+", "", line).strip().lower()] > max(4, pages // 20))]


def _join(lines: list[str]) -> list[str]:
    if not lines:
        return []
    width = sorted(len(line) for line in lines)[len(lines) * 3 // 4]
    paragraphs, buf = [], ""
    for line in lines:
        if _is_heading(line):
            if buf:
                paragraphs.append(buf)
            paragraphs.append(line)
            buf = ""
            continue
        if buf.endswith("-") and line[:1].islower():
            buf = buf[:-1] + line
        elif buf and re.search(r"[㐀-鿿]$", buf) and re.match(r"[㐀-鿿]", line):
            buf += line                                       # Chinese lines join without a space
        else:
            buf = f"{buf} {line}".strip()
        if _LINE_END.search(line) and len(line) < width * 0.8:
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)
    return paragraphs


def _outline(reader) -> list[tuple[str, int]]:
    try:
        items = reader.outline
    except Exception:
        return []
    out = []
    for item in items:
        if isinstance(item, list):
            continue                                          # nested: keep the top level
        try:
            out.append((_clean(item.title), reader.get_destination_page_number(item)))
        except Exception:
            continue
    return sorted(out, key=lambda t: t[1])


def parse_pdf(path: str | Path) -> Parsed:
    import logging

    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(path))
    lines = _pdf_lines(reader)
    title = ((reader.metadata.title if reader.metadata else None) or "").strip() or Path(path).stem.replace("_", " ")
    author = ((reader.metadata.author if reader.metadata else None) or "").strip()
    outline = _outline(reader)
    chapters: list[Chapter] = []
    if len(outline) >= 2:
        for n, (name, page) in enumerate(outline):
            stop = outline[n + 1][1] if n + 1 < len(outline) else len(reader.pages)
            chapters.append(Chapter(name, _join([line for p, line in lines if page <= p < stop])))
    else:
        chapters = split_text("\n\n".join(_join([line for _, line in lines])), title, roman=False, standalone=False)
    return Parsed(title, author, "", _tidy(chapters))


def parse(path: str | Path) -> Parsed:
    suffix = Path(path).suffix.lower()
    if suffix == ".epub":
        return parse_epub(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix in (".txt", ".md"):
        return parse_txt(path)
    raise ValueError(f"not a book file I can read: {Path(path).name} (EPUB, TXT or PDF)")
