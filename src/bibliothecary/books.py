"""Whole books: the shelf, where you are in each book, and three ways of reading one.

    ~/Bibliothecary/books/<title>/
      book.json        title, author, how it is read, its chapters, where you are, every session
      chapters/001.txt one chapter, paragraphs separated by blank lines (stays on this computer)
      summaries.json   one short summary per chapter, made only as far as the reader has read
                       (or all at once for a book read as "digest" or "excerpts")
      map.json         the whole-book map, for "digest"

Every session is still an ordinary reading folder in ``readings/``, with a ``book.json`` beside its
lesson saying which book and which paragraphs it covers, so the player, the reading report and the
Telegram buttons work as they do for an article. A session counts once its reading is finished;
then the place in the book moves on.

Three ways of reading (see docs/design/books.zh-CN.md):

  text      读原文: you read the text itself. The librarian stays quiet: a "previously" before you
            start (never anything past where you are), notes only on real difficulties, the cursor
            moving at reading pace, one or two open questions at the end.
  digest    拆书: a map of the whole book first, then a chapter or a theme at a time, explained;
            you need not read every sentence.
  excerpts  精华原文: the few passages of a chapter most worth reading in the author's own words,
            read closely; what lies between them is told in a sentence. Passages are whole
            paragraphs taken from the book by number, so nothing can be misquoted.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from margin import brain
from margin.lesson import Lesson, Step

from . import bookfile, library, report

MODES = ("text", "digest", "excerpts")
MODE_NAMES = {"text": ("读原文", "read the text"), "digest": ("拆书", "digest"),
              "excerpts": ("精华原文", "best passages")}
_MODE_WORDS = {"text": "text", "原文": "text", "读原文": "text", "read": "text",
               "digest": "digest", "拆书": "digest", "梗概": "digest", "摘要": "digest", "summary": "digest",
               "excerpts": "excerpts", "精华": "excerpts", "精华原文": "excerpts", "passages": "excerpts",
               "best": "excerpts"}
_lock = threading.RLock()


def mode_of(word: str) -> str | None:
    word = (word or "").strip().lower()
    return _MODE_WORDS.get(word) or next((m for k, m in _MODE_WORDS.items() if k in word), None)


def is_chinese(language: str) -> bool:
    language = (language or "").lower()
    return language.startswith("zh") or "chinese" in language or "中文" in language or "汉语" in language


def books_dir() -> Path:
    return library.home() / "books"


def judge(client, system: str, user: str) -> dict:
    """Requests that need judgement (the map, which passages, which notes, the "previously") use the
    stronger model when one is set (BIBLIOTHECARY_BOOK_MODEL, else BIBLIOTHECARY_CHAT_MODEL); bulk work
    such as chapter summaries stays on the main model."""
    model = os.environ.get("BIBLIOTHECARY_BOOK_MODEL") or os.environ.get("BIBLIOTHECARY_CHAT_MODEL") or None
    if model:
        try:
            return client.chat_json(system, user, model=model)
        except TypeError:
            pass                                       # a client without model choice (tests)
    return client.chat_json(system, user)


class _Judging:
    """A client whose chat_json goes to the judging model: lessons of a book are written once and read slowly."""

    def __init__(self, client) -> None:
        self.client = client

    def chat_json(self, system: str, user: str, **_) -> dict:
        return judge(self.client, system, user)

    def __getattr__(self, name):
        return getattr(self.client, name)


def minutes() -> int:
    try:
        return max(5, int(os.environ.get("BIBLIOTHECARY_BOOK_MINUTES", "20")))
    except ValueError:
        return 20


# reading speed in characters a minute: silent reading of Chinese, and English read by a second-
# language reader (about 150 words a minute)
SPEED = {"zh": 400, "en": 900}
DIGEST_CHARS = 60_000            # how much source a digest session covers at most
EXCERPT_CHARS = {"zh": 2500, "en": 6000}   # how much original text an excerpts session shows


@dataclass
class Book:
    folder: Path
    data: dict[str, Any]

    # ---- basics ----------------------------------------------------------------------
    @property
    def title(self) -> str:
        return self.data["title"]

    @property
    def mode(self) -> str:
        return self.data.get("mode") or "text"

    @property
    def lang(self) -> str:
        return "zh" if is_chinese(self.data.get("language", "")) else "en"

    @property
    def chapters(self) -> list[dict]:
        return self.data["chapters"]

    def chapter(self, i: int) -> list[str]:
        path = self.folder / "chapters" / f"{i + 1:03d}.txt"
        return [p.strip() for p in path.read_text(encoding="utf-8").split("\n\n") if p.strip()]

    @property
    def position(self) -> tuple[int, int]:
        p = self.data.get("position") or [0, 0]
        return int(p[0]), int(p[1])

    @property
    def furthest(self) -> tuple[int, int]:
        p = self.data.get("furthest") or [0, 0]
        return int(p[0]), int(p[1])

    @property
    def finished(self) -> bool:
        return self.position[0] >= len(self.chapters)

    def save(self) -> None:
        with _lock:
            tmp = self.folder / "book.json.tmp"
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.folder / "book.json")

    def _json(self, name: str) -> dict:
        path = self.folder / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def _write_json(self, name: str, data: dict) -> None:
        with _lock:
            (self.folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def summaries(self) -> dict[str, dict]:
        return self._json("summaries.json")

    def progress(self) -> str:
        """"第 3/12 章" style, with the share of the book read."""
        total = sum(c["size"] for c in self.chapters) or 1
        c, p = self.position
        done = sum(ch["size"] for ch in self.chapters[:c])
        if c < len(self.chapters) and p:
            done += sum(len(x) for x in self.chapter(c)[:p])
        return f"{min(c + 1, len(self.chapters))}/{len(self.chapters)} · {round(100 * done / total)}%"


# ---- the shelf ----------------------------------------------------------------------------
def shelf() -> list[Book]:
    root = books_dir()
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(root.iterdir()):
        path = folder / "book.json"
        if path.is_file():
            try:
                out.append(Book(folder, json.loads(path.read_text(encoding="utf-8"))))
            except json.JSONDecodeError:
                continue
    return out


def current() -> Book | None:
    """The book being read: the one used most recently that is neither finished nor paused."""
    live = [b for b in shelf() if b.data.get("status", "reading") == "reading" and not b.finished]
    return max(live, key=lambda b: b.data.get("used", ""), default=None)


def find(query: str) -> Book | None:
    q = (query or "").strip().lower()
    if not q:
        return current()
    def names(b: Book) -> list[str]:
        return [str(b.data.get(k) or "").lower() for k in ("title", "original_title", "catalog", "author", "file_name")] \
            + [b.folder.name.lower()]

    for book in shelf():
        if q in names(book):
            return book
    return next((b for b in shelf() if any(q in n for n in names(b))), None)


_BOOKISH = re.compile(r"^\s*(第.{1,4}[章回卷篇部]|卷.{1,3}|(chapter|lecture|part|book|letter)\b)", re.IGNORECASE)


def looks_like_book(path: str | Path) -> bool:
    """An EPUB always is. A TXT or PDF is when it is very long, or long with real chapters ("Chapter 3",
    "第三章"): a paper with sections (Introduction, Methods…) stays an article. /asbook overrides."""
    if Path(path).suffix.lower() == ".epub":
        return True
    try:
        parsed = bookfile.parse(path)
    except Exception:
        return False
    size = sum(c.size for c in parsed.chapters)
    chapters = sum(1 for c in parsed.chapters if _BOOKISH.match(c.title))
    return size > 200_000 or (size > 60_000 and chapters >= 3)



CLASSIFY = """You are a librarian looking at a book someone just brought in. From its title, author, contents
and opening, say what kind of book it is and how it is best read.
Return JSON: {{"kind": "fiction" | "essays" | "poetry" | "nonfiction", "mode": "text" | "digest",
"why": "one short sentence in {explain}, plain, saying what the book is (no praise)"}}.
"text" (read the text itself) suits fiction, essays, memoirs and poetry, where the writing is the point.
"digest" (explain the argument chapter by chapter) suits science, social science and other books
read for their ideas."""


def _classify(client, parsed: bookfile.Parsed, explain: str) -> dict:
    contents = "\n".join(f"- {c.title}" for c in parsed.chapters[:40])
    opening = " ".join(parsed.chapters[0].paragraphs)[:2500] if parsed.chapters else ""
    try:
        data = client.chat_json(CLASSIFY.format(explain=explain),
                                f"Title: {parsed.title}\nAuthor: {parsed.author}\n\nContents:\n{contents}\n\nOpening:\n{opening}")
    except Exception:
        return {}
    kind = data.get("kind") if data.get("kind") in ("fiction", "essays", "poetry", "nonfiction") else ""
    mode = data.get("mode") if data.get("mode") in ("text", "digest") else ""
    return {"kind": kind, "mode": mode, "why": str(data.get("why") or "").strip()}


def add(path: str | Path, *, client=None, title: str | None = None, mode: str | None = None,
        explain: str = "English", log=None) -> Book:
    """Put a book file on the shelf (or find it there already) and return it."""
    from .prepare import guess_language

    path = Path(path)
    parsed = bookfile.parse(path)
    if not parsed.chapters:
        raise ValueError(f"found no text in {path.name}")
    for book in shelf():                          # the same file again keeps its place
        if book.data.get("file_name") == path.name and len(book.chapters) == len(parsed.chapters):
            if mode in MODES:
                book.data["mode"] = mode
                book.save()
            return book
    name = title or parsed.title
    base = books_dir() / library.slug(name, 50)
    folder, n = base, 2
    while folder.exists():
        folder, n = base.with_name(f"{base.name}-{n}"), n + 1
    (folder / "chapters").mkdir(parents=True)
    for i, chapter in enumerate(parsed.chapters):
        text = "\n\n".join(p.replace("\n", " ") for p in chapter.paragraphs)
        (folder / "chapters" / f"{i + 1:03d}.txt").write_text(text + "\n", encoding="utf-8")
    sample = " ".join(p for c in parsed.chapters[:3] for p in c.paragraphs)[:6000]
    language = parsed.language or guess_language(sample)
    found = _classify(client, parsed, explain) if client is not None else {}
    data = {
        "title": name, "author": parsed.author, "language": language, "file_name": path.name,
        "added": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": found.get("kind", ""), "why": found.get("why", ""),
        "mode": mode if mode in MODES else (found.get("mode") or "text"),
        "chapters": [{"title": c.title or f"{i + 1}", "size": c.size} for i, c in enumerate(parsed.chapters)],
        "words": sum(len(re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", p)) for c in parsed.chapters for p in c.paragraphs),
        "position": [0, 0], "furthest": [0, 0], "sessions": [], "status": "reading",
        "used": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    book = Book(folder, data)
    book.save()
    if log:
        log(f"shelved “{name}”: {len(parsed.chapters)} chapters, {sum(c.size for c in parsed.chapters)} characters, "
            f"read as {book.mode}")
    return book


def set_mode(book: Book, mode: str) -> None:
    book.data["mode"] = mode
    book.data["used"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    book.save()


def set_status(book: Book, status: str) -> None:
    book.data["status"] = status
    if status == "reading":
        book.data["used"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    book.save()


# ---- progress -----------------------------------------------------------------------------
def _reading(name: str) -> Path:
    return library.readings_dir() / name


def sync(book: Book) -> Book:
    """Move the place in the book past every session that has been read."""
    changed = False
    for session in book.data.get("sessions", []):
        if session.get("done"):
            continue
        folder = _reading(session["reading"])
        if folder.is_dir() and library.status(folder) == "read":
            session["done"] = True
            if session.get("kind") == "map":
                book.data["mapped"] = True
            else:
                end = list(session["end"])
                if tuple(end) > book.position:
                    book.data["position"] = end
                if tuple(end) > book.furthest:
                    book.data["furthest"] = end
            changed = True
    if changed:
        if book.finished:
            book.data["status"] = "finished"
        book.save()
    return book


def sync_all() -> None:
    for book in shelf():
        if any(not s.get("done") for s in book.data.get("sessions", [])):
            sync(book)


def pending(book: Book) -> Path | None:
    """A session already prepared and not finished: read that before preparing another."""
    for session in reversed(book.data.get("sessions", [])):
        folder = _reading(session["reading"])
        if not session.get("done") and folder.is_dir() and library.status(folder) != "read":
            return folder
    return None


def up_next() -> Path | None:
    """What to read next: the open book's prepared part first; otherwise the oldest unread reading,
    leaving out parts of books that are paused or not the one being read."""
    book = current()
    if book is not None:
        waiting = pending(sync(book))
        if waiting is not None:
            return waiting
    elsewhere = {s["reading"] for b in shelf() if book is None or b.folder != book.folder
                 for s in b.data.get("sessions", [])}
    for folder in library.readings():
        if folder.name not in elsewhere and library.status(folder) != "read":
            return folder
    return None


Segment = tuple[int, int, int]          # (chapter, first paragraph, paragraph after the last)


def next_range(book: Book, mode: str | None = None) -> list[Segment]:
    """The paragraphs of the next session, from the current place: chapter-shaped where possible."""
    mode = mode or book.mode
    if mode == "text":
        budget = SPEED[book.lang] * minutes()
    else:
        budget = DIGEST_CHARS
    c, p = book.position
    segments: list[Segment] = []
    used = 0
    while c < len(book.chapters):
        paragraphs = book.chapter(c)
        rest = sum(len(x) for x in paragraphs[p:])
        if segments and (used >= budget * 0.5 or used + rest > budget):
            break                                          # a new chapter only to fill a short session
        if used + rest <= budget * 1.3:
            segments.append((c, p, len(paragraphs)))       # the rest of this chapter fits
            used += rest
            c, p = c + 1, 0
            continue
        end, size = p, 0
        while end < len(paragraphs) and (end == p or used + size + len(paragraphs[end]) <= budget):
            size += len(paragraphs[end])
            end += 1
        if len(paragraphs) - end <= 2:                     # do not leave a stub for tomorrow
            end = len(paragraphs)
        segments.append((c, p, end))
        break
    return segments


def _end_of(book: Book, segments: list[Segment]) -> list[int]:
    c, _, end = segments[-1]
    return [c + 1, 0] if end >= len(book.chapter(c)) else [c, end]


# ---- summaries and the map ------------------------------------------------------------------
SUMMARIZE = """You summarize chapters of a book for a librarian's notes, so later sessions can recall them.
For each chapter given, write in English:
  "summary": 3-6 plain sentences: what happens or what is argued, with the key names, examples and claims.
  "points": up to 4 short phrases worth remembering (terms, findings, turns of the plot).
  "people": for fiction or memoir, the people who appear, each "name: who they are" ([] otherwise).
Use only what is in the chapter text. Return JSON: {"chapters": [{"n": <number given>, "summary": "...",
"points": [...], "people": [...]}]}."""

BATCH_CHARS = 70_000


def ensure_summaries(client, book: Book, upto: int | None = None, log=None) -> dict[str, dict]:
    """Summaries of chapters [0, upto) (all when None), made only for the ones still missing."""
    have = book.summaries
    upto = len(book.chapters) if upto is None else min(upto, len(book.chapters))
    missing = [i for i in range(upto) if str(i) not in have]
    if not missing or client is None:
        return have
    batches, batch, size = [], [], 0
    for i in missing:
        n = min(book.chapters[i]["size"], BATCH_CHARS)
        if batch and size + n > BATCH_CHARS:
            batches.append(batch)
            batch, size = [], 0
        batch.append(i)
        size += n
    if batch:
        batches.append(batch)
    if log:
        log(f"summarizing {len(missing)} chapters of “{book.title}” in {len(batches)} requests…")

    def run(batch: list[int]) -> dict[str, dict]:
        text = "\n\n".join(f"## [{i + 1}] {book.chapters[i]['title']}\n" + "\n".join(book.chapter(i))[:BATCH_CHARS]
                           for i in batch)
        try:
            data = client.chat_json(SUMMARIZE, f"Book: {book.title} ({book.data.get('author', '')})\n\n{text}")
        except Exception as err:
            if log:
                log(f"summary failed: {err}")
            return {}
        out = {}
        for item in data.get("chapters") or []:
            try:
                i = int(item.get("n")) - 1
            except (TypeError, ValueError):
                continue
            if i in batch:
                out[str(i)] = {"summary": str(item.get("summary") or "").strip(),
                               "points": [str(x) for x in (item.get("points") or [])][:4],
                               "people": [str(x) for x in (item.get("people") or [])][:12]}
        return out

    with ThreadPoolExecutor(max_workers=4) as pool:
        for found in pool.map(run, batches):
            have.update(found)
            book._write_json("summaries.json", have)      # kept as it comes: an interrupted run resumes
    return have


def _read_so_far(book: Book, upto: int, size: int = 6000) -> str:
    """The summaries of chapters before ``upto``, newest kept when it gets long."""
    have = book.summaries
    lines = [f"Ch. {i + 1} {book.chapters[i]['title']}: {have[str(i)]['summary']}"
             for i in range(upto) if str(i) in have]
    text = "\n".join(lines)
    return text if len(text) <= size else "…" + text[-size:]


MAP = """You make a map of a whole book for a reader who will go through it with you, chapter by chapter.
From the chapter summaries, return JSON in {explain}:
{{"question": "the question the book tries to answer, one sentence",
  "answer": "the book's answer in two or three sentences",
  "parts": [{{"title": "short name of a part", "chapters": [first, last], "gist": "what this part argues or shows, 1-2 sentences"}}],
  "key": [{{"chapter": n, "why": "why this chapter matters most, one sentence"}}],
  "skip": "which chapters a busy reader can skim, and why, one sentence, or empty"}}
Group the chapters into 2-6 parts that follow the book's own structure. The numbers in brackets are only for
"chapters" and "key"; in any text, name a chapter by its title, never by a number. Plain words, no praise."""


def ensure_map(client, book: Book, explain: str, log=None) -> dict:
    data = book._json("map.json")
    if data.get("parts") or client is None:
        return data
    ensure_summaries(client, book, log=log)
    have = book.summaries
    lines = "\n".join(f"[{i + 1}] {c['title']}: {have.get(str(i), {}).get('summary', '')}"
                      for i, c in enumerate(book.chapters))
    data = judge(client, MAP.format(explain=explain), f"Book: {book.title} by {book.data.get('author', '')}\n\n{lines}")
    data["parts"] = _tile(data.get("parts") or [], len(book.chapters))
    book._write_json("map.json", data)
    return data


def _tile(parts: list, n: int) -> list[dict]:
    """Parts in order, each running up to where the next begins, so they cover the book once."""
    good = []
    for part in parts:
        try:
            first = max(1, min(n, int((part.get("chapters") or [])[0])))
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        good.append({**part, "chapters": [first, first]})
    good.sort(key=lambda part: part["chapters"][0])
    out = []
    for k, part in enumerate(good):
        if out and part["chapters"][0] == out[-1]["chapters"][0]:
            continue
        last = (good[k + 1]["chapters"][0] - 1) if k + 1 < len(good) else n
        out.append({**part, "chapters": [part["chapters"][0], max(part["chapters"][0], last)]})
    return out


def _map_paragraphs(book: Book, data: dict, chinese: bool) -> list[str]:
    out = []
    if data.get("question"):
        out.append(("这本书想回答：" if chinese else "The question: ") + str(data["question"]))
    if data.get("answer"):
        out.append(("它的回答：" if chinese else "Its answer: ") + str(data["answer"]))
    def name(n) -> str:
        return book.chapters[n - 1]["title"].rstrip(".") if isinstance(n, int) and 1 <= n <= len(book.chapters) else ""

    for part in data.get("parts") or []:
        chapters = [n for n in (part.get("chapters") or []) if name(n)]
        span = (name(chapters[0]) if chapters[0] == chapters[-1] else f"{name(chapters[0])} — {name(chapters[-1])}") \
            if chapters else ""
        out.append(f"{part.get('title', '')}（{span}）：{part.get('gist', '')}" if chinese
                   else f"{part.get('title', '')} ({span}): {part.get('gist', '')}")
    for item in data.get("key") or []:
        if name(item.get("chapter")):
            out.append((f"重点：{name(item['chapter'])}。" if chinese else f"Key: {name(item['chapter'])}. ")
                       + str(item.get("why", "")))
    if data.get("skip"):
        out.append(("可以略读：" if chinese else "Skim: ") + str(data["skip"]))
    return [p for p in out if p.strip()]


# ---- a "previously" that never goes past where you are ----------------------------------------
RECAP = """Someone is coming back to a book they are reading, and you say a short "previously" before they go on.
Use ONLY the notes and the last lines below: they are everything the reader has read. Never mention, hint at
or guess anything that comes later in the book, even if you know the book.
Return JSON in {explain}: {{"recap": ["1-3 short spoken sentences: where we are and what just happened or was argued"],
"people": ["for fiction or memoir: up to 6 people met so far, each 'name: who they are', else empty"]}}.
Plain, concrete words. No praise, no questions."""


def recap(client, book: Book, explain: str, log=None) -> dict:
    c, p = book.position
    if (c, p) == (0, 0) or client is None:
        return {}
    ensure_summaries(client, book, upto=c, log=log)
    tail = ""
    if p:
        tail = "\n".join(book.chapter(c)[:p])[-3000:]
    elif c:
        tail = "\n".join(book.chapter(c - 1))[-3000:]
    try:
        data = judge(client, RECAP.format(explain=explain),
                                f"Book: {book.title}\n\nNotes on the chapters read so far:\n{_read_so_far(book, c)}\n\n"
                                f"The last lines read:\n{tail}")
    except Exception as err:
        if log:
            log(f"recap failed: {err}")
        return {}
    return {"recap": [str(x) for x in data.get("recap") or [] if str(x).strip()][:3],
            "people": [str(x) for x in data.get("people") or [] if str(x).strip()][:6]}


# ---- what the answering model is told ----------------------------------------------------------
def _guide(book: Book, mode: str, segments: list[Segment]) -> str:
    c = segments[0][0]
    where = ", ".join(f"chapter {s[0] + 1} ({book.chapters[s[0]]['title']})" for s in segments)
    lines = [f"This session is part of a book: “{book.title}” by {book.data.get('author') or 'unknown'}, {where}."]
    so_far = _read_so_far(book, c, 3000)
    if so_far:
        lines.append("What the reader has read before tonight, chapter by chapter:\n" + so_far)
    if mode == "text" or book.data.get("kind") in ("fiction", "essays", "poetry"):
        lines.append("The reader is reading this book for the first time. Never reveal, hint at or confirm anything "
                     "that happens or is said later in the book, even if you know the book and they ask; say they "
                     "have not got there yet. Do not look up this book's plot on the web.")
    if mode == "text":
        lines.append("They are reading the text themselves: keep answers short and go back to the text. The questions "
                     "at the end are open: there is no right answer. Respond to what they noticed, point to a line "
                     "that bears on it, and never mark an answer right or wrong.")
    if mode == "digest":
        mapped = book._json("map.json")
        if mapped.get("question"):
            lines.append(f"The book's question: {mapped['question']} Its answer: {mapped.get('answer', '')}")
    return "\n\n".join(lines)


# ---- making a session ---------------------------------------------------------------------
TEXT_SYSTEM = """You sit next to someone reading a book in its own words. They want to read the text themselves,
not hear it retold. Your job is to stay out of the way and help only where a reader would really get stuck.

The text is below, with sentence ids. Return JSON in {explain}:
{{"opening": "one short spoken sentence before they start, naming tonight's part ({part}); no summary, no praise",
  "notes": [{{"focus": "p3.s2", "mark": "words copied exactly from that sentence", "note": "at most 25 words",
             "say": "one short spoken sentence"}}],
  "questions": [{{"question": "an open question about what they just read", "about": "what a thoughtful answer might touch on"}}],
  "goodbye": "one short line"}}
Notes: 0 to {n_notes}, in reading order, ONLY for real difficulties: an allusion or reference, an old or rare word,
a foreign phrase, a historical fact the text assumes, a name the reader cannot place, a sentence whose grammar is
hard{translate}. A note states a fact (what a word means, who someone is, what an allusion refers to); it never
interprets the author or guesses at their motives. Never summarize, never explain what is plain, never tell what
comes next in the book.
Questions: {n_questions}, open ("what did you make of...", "why do you think..."), never a test of facts.
{style}"""


def _lesson(book: Book, segments: list[Segment], title: str, explain: str) -> Lesson:
    paragraphs = []
    for c, start, end in segments:
        if start == 0:
            paragraphs.append({"text": book.chapters[c]["title"]})
        paragraphs += [{"text": p} for p in book.chapter(c)[start:end]]
    language = "zh-CN" if book.lang == "zh" else "en"
    return Lesson.from_dict({"title": title, "source": book.data.get("file_name", ""), "language": language,
                             "explain_language": explain, "paragraphs": paragraphs, "steps": []})


def _title(book: Book, segments: list[Segment], chinese: bool) -> str:
    names = [book.chapters[c]["title"] for c, _, _ in segments]
    first = names[0] + (("（续）" if chinese else " (cont.)") if segments[0][1] > 0 else "")
    if len(names) > 1 and all(len(n) <= 8 for n in names):
        return f"{book.title} · {first}–{names[-1]}"                # numbered parts: "I–IV"
    if len(names) == 2:
        first += ("、" if chinese else ", ") + names[1]
    elif len(names) > 2:
        first += f" 等 {len(names)} 章" if chinese else f" and {len(names) - 1} more"
    return f"{book.title} · {first}"


def _text_steps(client, book: Book, lesson: Lesson, explain: str, review: int, recap_data: dict,
                aloud: bool, bedtime: bool) -> list[Step]:
    chinese_reader = is_chinese(explain)
    translate = (", or an English phrase a Chinese reader may not know (translate it)"
                 if book.lang == "en" and chinese_reader else "")
    n_notes = max(2, min(10, len(lesson.sentence_ids()) // 25 + 2))
    part = lesson.title.split(" · ", 1)[-1]
    system = TEXT_SYSTEM.format(explain=explain, n_notes=n_notes, n_questions=f"0 to {max(0, min(review, 2))}",
                                translate=translate, style=brain.STYLE, part=part)
    data = judge(client, system, lesson.context())
    steps: list[Step] = []
    for line in recap_data.get("recap", []):
        steps.append(Step(say=line, part="preview"))
    if recap_data.get("people"):
        steps.append(Step(say=("出场的人：" if chinese_reader else "People so far: ") + "；".join(recap_data["people"]),
                          part="preview"))
    if str(data.get("opening") or "").strip():
        steps.append(Step(say=str(data["opening"]).strip()))
    notes: dict[int, list[Step]] = {}
    for step in brain.clean_steps(lesson, data.get("notes") or []):
        if step.focus:
            p = int(step.focus.split(".")[0][1:]) - 1
            notes.setdefault(p, []).append(step)
    speed = SPEED[book.lang] / 60.0
    for p, para in enumerate(lesson.paragraphs):
        steps.extend(notes.get(p, []))
        if aloud:
            for s, sentence in enumerate(para):
                steps.append(Step(say=sentence, focus=f"p{p + 1}.s{s + 1}"))
        else:
            size = sum(len(s) for s in para)
            focus = notes[p][-1].focus if notes.get(p) else f"p{p + 1}.s1"
            steps.append(Step(say="", focus=focus, pause=round(max(2.0, size / speed), 1)))
    for item in (data.get("questions") or [])[:max(0, min(review, 2))]:
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            steps.append(Step(say=str(item["question"]).strip(), part="review",
                              expect=brain.OPEN + str(item.get("about") or "").strip()))
    goodbye = str(data.get("goodbye") or "").strip()
    if goodbye:
        steps.append(Step(say=goodbye + (("晚安。" if chinese_reader else " Good night.") if bedtime and "晚安" not in goodbye
                                          and "night" not in goodbye.lower() else ""), part="review"))
    return steps


PICK = """You choose the passages of a book chapter most worth reading in the author's own words, for someone
who will not read the whole chapter. The paragraphs are numbered. Choose {n} passages, in order, each one
or two paragraphs, together at most about {budget} characters, spread over the whole text (its beginning,
middle and end), so that together they carry the chapter's line of thought. Prefer: the author's
central claims in their own words, key definitions, the strongest evidence or example, a turning point in the
argument or story, a sentence that is memorable for how it is written. Skip footnotes, tables and lists.
Return JSON in {explain}: {{"picks": [{{"from": n, "to": n, "why": "why this passage, one short sentence",
"before": "what the author does between the previous passage (or the chapter's start) and this one, one or two sentences"}}],
"after": "what the rest of the chapter does after the last passage, one sentence"}}"""


def _pick(client, book: Book, segments: list[Segment], explain: str) -> tuple[list[list[tuple[int, int]]], list[dict], str]:
    """The chosen passages as groups of (chapter, paragraph), what to say before each, and after the last."""
    numbered, index = [], []
    for c, start, end in segments:
        for i, p in enumerate(book.chapter(c)[start:end], start):
            index.append((c, i))
            numbered.append(f"[{len(index)}] {p}")
    budget = EXCERPT_CHARS[book.lang]
    data = judge(client, PICK.format(n="3-6", budget=budget, explain=explain),
                            f"Book: {book.title}\n\n" + "\n\n".join(numbered))
    picks, info, used, last = [], [], 0, 0
    for item in data.get("picks") or []:
        try:
            a, b = int(item.get("from")), int(item.get("to", item.get("from")))
        except (TypeError, ValueError):
            continue
        a, b = max(a, last + 1), min(b, len(index), max(a, last + 1) + 1)
        if a > b or a > len(index):
            continue
        size = sum(len(book.chapter(index[k - 1][0])[index[k - 1][1]]) for k in range(a, b + 1))
        if picks and used + size > budget * 1.2:
            continue                                   # too long: a later, shorter passage may still fit
        picks.append((a, b, size))
        info.append({"why": str(item.get("why") or ""), "before": str(item.get("before") or "")})
        used += size
        last = b
    groups = [[(index[k - 1][0], index[k - 1][1]) for k in range(a, b + 1)] for a, b, _ in picks]
    return groups, info, str(data.get("after") or "").strip()


EXCERPT_GUIDE = """These paragraphs are not the whole chapter: they are {n} passages chosen from it, shown in the
author's own words. Read them closely with the listener: what each passage says, why it matters, the words that carry
it; mark the key words. What lies between the passages is said separately: do not describe it. Why each was chosen:
{why}
Never present your own words as the author's: quote only what is on screen."""


def _bridge(steps: list[Step], groups: list[list], info: list[dict], after: str) -> list[Step]:
    """Before each passage, a sentence on what the author does in between; after the last, what follows."""
    starts, n = [], 0
    for group in groups:
        starts.append(n + 1)                         # lesson paragraph number where the passage begins
        n += len(group)

    def para(step: Step) -> int:
        return int(step.focus.split(".")[0][1:]) if step.focus else 0

    out, g, seen_reading = [], 0, False

    def flush(upto: int) -> None:
        nonlocal g
        while g < len(starts) and starts[g] <= upto:
            if info[g].get("before"):
                out.append(Step(say=info[g]["before"], focus=f"p{starts[g]}.s1"))
            g += 1

    for step in steps:
        if step.part is None:
            seen_reading = True
            if step.focus:
                flush(para(step))
        elif step.part == "review" and seen_reading and g <= len(starts):
            flush(10 ** 6)                            # passages no step talked about: still introduced, in order
            if after:
                out.append(Step(say=after))
                after = ""
        out.append(step)
    flush(10 ** 6)
    if after:
        out.append(Step(say=after))
    return out


def set_aside(book: Book, folder: Path) -> None:
    """A prepared session that will not be read (the way of reading changed): moved out of the readings, not deleted."""
    target = library.readings_dir() / "_set_aside"
    target.mkdir(parents=True, exist_ok=True)
    if folder.is_dir():
        dest, n = target / folder.name, 2
        while dest.exists():
            dest, n = target / f"{folder.name}-{n}", n + 1
        shutil.move(str(folder), str(dest))
    with _lock:
        for session in book.data.get("sessions", []):
            if session["reading"] == folder.name:
                session.update(done=True, set_aside=True)
        book.save()


def prepare_next(client, book: Book, *, explain: str = "English", bedtime: bool = False, review: int = 3,
                 mode: str | None = None, aloud: bool = False, again: bool = False, log=None) -> Path:
    """Prepare the next session of a book as a reading folder (or return the one still waiting).

    ``again``, or a different way of reading than the waiting session's: that one is set aside and
    the same place in the book is prepared anew."""
    sync(book)
    waiting = pending(book)
    if waiting is not None:
        marker = book_of(waiting) or {}
        started = library.status(waiting) == "started"
        same = (mode or book.mode) == marker.get("mode", book.mode)
        if started or (same and not again):
            return waiting                            # opened already (finish it first), or nothing changed
        set_aside(book, waiting)
    mode = mode or book.mode
    if book.finished:
        raise ValueError(f"“{book.title}” is finished")
    chinese = is_chinese(explain)
    book.data["used"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    if mode == "digest" and not book.data.get("mapped") and book.position == (0, 0) \
            and not any(s.get("kind") == "map" and not s.get("set_aside") for s in book.data.get("sessions", [])):
        mapped = ensure_map(client, book, explain, log=log)
        title = f"{book.title} · " + ("全书地图" if chinese else "Map of the book")
        lesson = brain.build_lesson(_Judging(client), title, "\n\n".join(_map_paragraphs(book, mapped, chinese)),
                                    explain_language=explain, source=book.data.get("file_name", ""),
                                    language="zh-CN" if chinese else "en", bedtime=bedtime, preview=False,
                                    review=min(review, 1),
                                    guide="This is the first session of a book: its map. Tell the listener what the "
                                          "book is about and how it is built, so they can decide how to read it.")
        lesson.guide = _guide(book, mode, [(0, 0, 0)])
        return _store(book, lesson, mode, [(0, 0, 0)], kind="map")

    segments = next_range(book, mode)
    if not segments:
        raise ValueError(f"“{book.title}” is finished")
    title = _title(book, segments, chinese)
    if mode == "text":
        lesson = _lesson(book, segments, title, explain)
        lesson.steps = _text_steps(client, book, lesson, explain, review, recap(client, book, explain, log=log),
                                   aloud, bedtime)
    elif mode == "excerpts":
        ensure_summaries(client, book, upto=segments[-1][0] + 1, log=log)
        groups, info, after = _pick(client, book, segments, explain)
        if not groups:
            raise ValueError("no passages were chosen")
        paragraphs = [book.chapter(c)[i] for group in groups for c, i in group]
        why = "\n".join(f"- passage {n + 1}: {x['why']}" for n, x in enumerate(info))
        lesson = brain.build_lesson(_Judging(client), title + (" · 精华原文" if chinese else " · best passages"),
                                    "\n\n".join(paragraphs), explain_language=explain,
                                    source=book.data.get("file_name", ""),
                                    language="zh-CN" if book.lang == "zh" else "en", bedtime=bedtime,
                                    preview=bool(book.position != (0, 0)), review=review,
                                    known=_read_so_far(book, segments[0][0], 1500),
                                    guide=EXCERPT_GUIDE.format(n=len(info), why=why))
        lesson.steps = _bridge(lesson.steps, groups, info, after)
    else:                                             # digest
        text = "\n\n".join(p for c, a, b in segments for p in book.chapter(c)[a:b])
        lesson = brain.build_lesson(_Judging(client), title, text, explain_language=explain,
                                    source=book.data.get("file_name", ""),
                                    language="zh-CN" if book.lang == "zh" else "en", bedtime=bedtime,
                                    preview=True, review=review, known=_read_so_far(book, segments[0][0], 1500),
                                    guide="This is one chapter of a book read as a digest: the listener does not read "
                                          "every sentence. Explain the author's argument, the evidence and the examples, "
                                          "in the order of the chapter; focus the sentences where the author states a "
                                          "conclusion. Long chapters are cut: cover only the text given.")
    lesson.guide = _guide(book, mode, segments)
    return _store(book, lesson, mode, segments)


def _store(book: Book, lesson: Lesson, mode: str, segments: list[Segment], kind: str = "read") -> Path:
    folder = library.new_reading(lesson)
    marker = {"book": book.folder.name, "title": book.title, "mode": mode, "kind": kind,
              "segments": [list(s) for s in segments]}
    (folder / "book.json").write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.write(folder)
    end = list(book.position) if kind == "map" else _end_of(book, segments)
    with _lock:
        book.data.setdefault("sessions", []).append({
            "reading": folder.name, "mode": mode, "kind": kind,
            "start": list(book.position), "end": end,
            "prepared": dt.datetime.now().astimezone().isoformat(timespec="seconds")})
        book.save()
    return folder


def book_of(folder: Path) -> dict | None:
    """The book marker of a reading folder, if it is a book session."""
    path = folder / "book.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def describe(book: Book, chinese: bool) -> str:
    name = MODE_NAMES.get(book.mode, (book.mode, book.mode))[0 if chinese else 1]
    size = sum(c["size"] for c in book.chapters)
    words = book.data.get("words") or round(size / 6)
    amount = (f"约 {round(size / 10000, 1)} 万字" if book.lang == "zh" else
              (f"约 {round(words / 10000, 1)} 万词" if words >= 10000 else f"约 {round(words, -2)} 词")) if chinese \
        else (f"about {max(1, round(words / 1000))}k words" if book.lang == "en" else f"about {size // 1000}k characters")
    head = (f"《{book.title}》" + (f"（{book.data['author']}）" if book.data.get("author") else "")
            + f"，{len(book.chapters)} 章，{amount}。读法：{name}，进度 {book.progress()}。") if chinese \
        else (f"“{book.title}”" + (f" by {book.data['author']}" if book.data.get("author") else "")
              + f": {len(book.chapters)} chapters, {amount}. Read as: {name}. Progress {book.progress()}.")
    return head
