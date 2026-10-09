"""Whole books: reading the files, the shelf, the place in the book, and the three ways of reading."""

import json
import re
import zipfile

import pytest

from bibliothecary import bookfile, books, library, report
from margin import brain
from margin.lesson import Lesson


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_HOME", str(tmp_path / "lib"))
    monkeypatch.setenv("BIBLIOTHECARY_BOOK_MINUTES", "20")
    return tmp_path / "lib"


def _xhtml(body: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title>'
            f"</head><body>{body}</body></html>")


def make_epub(path, chapters, *, gutenberg=False):
    """A small EPUB 3: one XHTML file per chapter, a nav, and optionally Gutenberg's wrapper."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                   'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        items, refs, nav = [], [], []
        files = [("front", "Contents", "<h2>Contents</h2><p>Chapter One</p><p>Chapter Two</p>")]
        if gutenberg:
            files.insert(0, ("pg-header", "", "<p>The Project Gutenberg eBook of a Test.</p>"
                                              "<p>*** START OF THE PROJECT GUTENBERG EBOOK A TEST ***</p>"))
        for n, (title, paragraphs) in enumerate(chapters, 1):
            files.append((f"ch{n}", title, f"<h2>{title}</h2>" + "".join(f"<p>{p}</p>" for p in paragraphs)))
        if gutenberg:
            files.append(("pg-footer", "", "<p>*** END OF THE PROJECT GUTENBERG EBOOK A TEST ***</p>"
                                           "<p>The Full Project Gutenberg License, all of it.</p>"))
        for name, title, body in files:
            z.writestr(f"OEBPS/{name}.xhtml", _xhtml(body))
            items.append(f'<item id="{name}" href="{name}.xhtml" media-type="application/xhtml+xml"/>')
            refs.append(f'<itemref idref="{name}"/>')
            if title:
                nav.append(f'<li><a href="{name}.xhtml">{title}</a></li>')
        z.writestr("OEBPS/nav.xhtml", _xhtml(f'<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc">'
                                             f'<ol>{"".join(nav)}</ol></nav>'))
        items.append('<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A Test Book</dc:title>'
                   '<dc:creator>Ann Author</dc:creator><dc:language>en</dc:language></metadata>'
                   f'<manifest>{"".join(items)}</manifest><spine>{"".join(refs)}</spine></package>')
    return path


def sentences(word, n, size=60):
    return [f"{word.capitalize()} paragraph {i} says something about {word} " + "and more words " * (size // 15) + "."
            for i in range(1, n + 1)]


class FakeClient:
    """Answers each kind of request the way a model would, and keeps every request."""

    def __init__(self, kind="nonfiction", mode="digest"):
        self.calls = []
        self.kind, self.mode = kind, mode

    def chat_json(self, system, user, **_):
        self.calls.append((system, user))
        if "how it is best read" in system:
            return {"kind": self.kind, "mode": self.mode, "why": "A test book."}
        if "librarian's notes" in system:
            numbers = [int(n) for n in re.findall(r"^## \[(\d+)\]", user, re.MULTILINE)]
            return {"chapters": [{"n": n, "summary": f"Summary of chapter {n}.", "points": ["p"], "people": []}
                                 for n in numbers]}
        if "map of a whole book" in system:
            return {"question": "What is tested?", "answer": "Everything.",
                    "parts": [{"title": "All", "chapters": [1, 3], "gist": "The whole thing."}],
                    "key": [{"chapter": 2, "why": "It matters."}], "skip": ""}
        if '"previously"' in system:
            return {"recap": ["Last time: the first chapter."], "people": []}
        if "stay out of the way" in system:
            return {"opening": "Here is the next part.",
                    "notes": [{"focus": "p2.s1", "mark": "paragraph", "note": "A word explained.", "say": "One note."}],
                    "questions": [{"question": "What did you notice?", "about": "the ending"}],
                    "goodbye": "That's all."}
        if "passages of a book chapter" in system:
            return {"picks": [{"from": 2, "to": 2, "why": "central", "before": "The author opens."},
                              {"from": 4, "to": 5, "why": "evidence", "before": "Then examples."}],
                    "after": "It ends."}
        return {"preview": [{"say": "Some background."}], "steps": [{"say": "It says this.", "focus": "p1.s1"}],
                "review": [{"question": "What is it?", "answer": "This."}], "goodbye": "Bye."}


def finish(folder):
    """Mark a reading as read, the way the player's log does."""
    with (folder / "session.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": "2026-10-09T21:00:00", "kind": "start"}) + "\n")
        f.write(json.dumps({"t": "2026-10-09T21:20:00", "kind": "end"}) + "\n")


# ---- reading files --------------------------------------------------------------------------
def test_epub_chapters_follow_the_contents_and_leave_out_the_wrapper(tmp_path):
    path = make_epub(tmp_path / "t.epub", [("Chapter One", sentences("one", 6)), ("Chapter Two", sentences("two", 6))],
                     gutenberg=True)
    parsed = bookfile.parse(path)
    assert (parsed.title, parsed.author, parsed.language) == ("A Test Book", "Ann Author", "en")
    assert [c.title for c in parsed.chapters] == ["Chapter One", "Chapter Two"]
    assert parsed.chapters[0].paragraphs[0].startswith("One paragraph 1")       # the heading is the title
    text = " ".join(p for c in parsed.chapters for p in c.paragraphs)
    assert "Gutenberg" not in text and "License" not in text


def test_txt_chapters_from_headings_in_any_encoding(tmp_path):
    body = "书名\n\n" + "\n\n".join(f"第{n}章 开始\n" + "\n".join(f"这是第{n}章的一段很长的文字，" * 6 for _ in range(5))
                                    for n in "一二三")
    path = tmp_path / "书.txt"
    path.write_bytes(body.encode("gb18030"))
    parsed = bookfile.parse(path)
    assert [c.title for c in parsed.chapters] == ["第一章 开始", "第二章 开始", "第三章 开始"]
    assert len(parsed.chapters[1].paragraphs) == 5


def test_txt_short_title_lines_standing_alone_are_chapters(tmp_path):
    pieces = ["小引", "狗·猫·鼠", "阿长与《山海经》", "后记"]
    body = "朝花夕拾\n鲁迅\n\n" + "\n\n".join(f"{t}\n\n" + "\n".join(["一段回忆，写得很长很长，" * 10] * 4) for t in pieces)
    path = tmp_path / "散文.txt"
    path.write_text(body, encoding="utf-8")
    assert [c.title for c in bookfile.parse(path).chapters] == pieces


# ---- the shelf and the place in the book -----------------------------------------------------
def test_text_mode_reads_the_original_quietly_and_moves_on_only_when_read(home, tmp_path):
    path = make_epub(tmp_path / "novel.epub", [(f"Chapter {n}", sentences(w, 8, size=1500)) for n, w in
                                                 enumerate(["one", "two", "three"], 1)])
    client = FakeClient(kind="fiction", mode="text")
    book = books.add(path, client=client, explain="English")
    assert book.mode == "text" and book.data["kind"] == "fiction"
    assert books.add(path).folder == book.folder                 # the same file again: the same book

    first = books.prepare_next(client, book)
    lesson = Lesson.load(first / "lesson.json")
    original = book.chapter(0)
    assert [" ".join(p) for p in lesson.paragraphs[1:]] == original           # the text itself, word for word
    assert not [s for s in lesson.steps if s.part == "preview"]               # nothing to recall yet
    paced = [s for s in lesson.steps if not s.say and s.pause]
    assert len(paced) == len(lesson.paragraphs)                               # the cursor moves at reading pace
    assert any(s.note == "A word explained." for s in lesson.steps)
    open_q = [s for s in lesson.steps if s.expect]
    assert open_q and open_q[0].expect.startswith(brain.OPEN)
    assert "Never reveal" in lesson.guide
    assert books.book_of(first)["book"] == book.folder.name

    assert books.prepare_next(client, book) == first          # not read yet: the same session again
    assert books.sync(book).position == (0, 0)
    finish(first)
    assert books.sync(book).position == (1, 0)

    client.calls.clear()
    second = books.prepare_next(client, book)
    lesson = Lesson.load(second / "lesson.json")
    assert lesson.paragraphs[0] == ["Chapter 2"]
    assert [s.say for s in lesson.steps if s.part == "preview"] == ["Last time: the first chapter."]
    summarized = [u for s, u in client.calls if "librarian's notes" in s]
    assert summarized and "## [1]" in summarized[0] and "## [2]" not in summarized[0]   # nothing past the place
    assert "Summary of chapter 1." in lesson.guide and "chapter 3" not in lesson.guide.lower()


def test_digest_starts_with_the_map_then_goes_chapter_by_chapter(home, tmp_path):
    path = make_epub(tmp_path / "science.epub", [(f"Chapter {n}", sentences(w, 8)) for n, w in
                                                   enumerate(["cells", "nerves", "brains"], 1)])
    client = FakeClient()
    book = books.add(path, client=client)
    assert book.mode == "digest"
    first = books.prepare_next(client, book)
    assert books.book_of(first)["kind"] == "map"
    shown = " ".join(" ".join(p) for p in Lesson.load(first / "lesson.json").paragraphs)
    assert "What is tested?" in shown and "Key: Chapter 2" in shown
    finish(first)
    second = books.prepare_next(client, book)
    marker = books.book_of(second)
    assert marker["kind"] == "read" and marker["segments"][0][0] == 0
    system = [s for s, _ in client.calls if "calm, curious reading companion" in s][-1]
    assert "read as a digest" in system


def test_excerpts_are_whole_paragraphs_of_the_book(home, tmp_path):
    path = make_epub(tmp_path / "essays.epub", [("Essay", sentences("essay", 8))])
    client = FakeClient(kind="essays", mode="text")
    book = books.add(path, client=client, mode="excerpts")
    folder = books.prepare_next(client, book)
    lesson = Lesson.load(folder / "lesson.json")
    shown = [" ".join(p) for p in lesson.paragraphs]
    chapter = book.chapter(0)
    assert shown == [chapter[1], chapter[3], chapter[4]]                 # picks 2, 4-5, never rewritten
    said = [s.say for s in lesson.steps]
    assert said.index("The author opens.") < said.index("It says this.") and "Then examples." in said
    assert "It ends." in said


def test_a_long_chapter_is_cut_and_short_ones_are_packed(home, tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_BOOK_MINUTES", "5")                 # 4500 characters of English
    long = sentences("long", 40, size=300)
    short = [(f"Short {n}", sentences("short", 3)) for n in range(4)]
    path = make_epub(tmp_path / "mixed.epub", [("Long", long)] + short)
    book = books.add(path)
    first = books.next_range(book, "text")
    assert len(first) == 1 and first[0][0] == 0 and 0 < first[0][2] < len(book.chapter(0))
    book.data["position"] = [1, 0]
    packed = books.next_range(book, "text")
    assert len(packed) > 1 and all(start == 0 for _, start, _ in packed)


def test_open_questions_are_answered_not_graded(home):
    review = {"question": "What did you notice?", "expect": brain.OPEN + "the ending"}
    text = brain._review(review)
    assert "no right answer" in text and "Never say whether it is right" in text
    assert "A good answer says" in brain._review({"question": "q", "expect": "a"})


def test_report_shows_open_questions_as_something_to_think_about(home, tmp_path):
    path = make_epub(tmp_path / "novel.epub", [("Chapter 1", sentences("one", 6))])
    client = FakeClient(kind="fiction", mode="text")
    book = books.add(path, client=client)
    folder = books.prepare_next(client, book)
    finish(folder)
    text = report.write(folder).read_text(encoding="utf-8")
    assert "To think about" in text or "可以想想" in text
    assert "(open question)" not in text
    assert library.status(folder) == "read"


def test_changing_the_way_of_reading_sets_the_waiting_session_aside(home, tmp_path):
    path = make_epub(tmp_path / "essays.epub", [("Essay", sentences("essay", 8))])
    client = FakeClient(kind="essays", mode="text")
    book = books.add(path, client=client)
    first = books.prepare_next(client, book)
    assert books.prepare_next(client, book) == first
    books.set_mode(book, "excerpts")
    second = books.prepare_next(client, book)
    assert second != first and not first.exists()
    assert (library.readings_dir() / "_set_aside" / first.name / "lesson.json").is_file()   # kept, not deleted
    assert library.next_unread() == second
    assert books.book_of(second)["mode"] == "excerpts" and book.position == (0, 0)


# ---- in Telegram ------------------------------------------------------------------------------
class ChatBot:
    def __init__(self, files):
        self.sent, self.files, self.downloads = [], [], files

    def send(self, chat, text, buttons=None):
        self.sent.append(text)

    def send_file(self, chat, path, caption=""):
        self.files.append(path)

    def typing(self, chat):
        pass

    def download(self, file_id):
        return self.downloads[file_id]


def _librarian(home, files, client, clock="2026-10-09T10:00"):
    import datetime as dt

    from bibliothecary import telegram

    bot = ChatBot(files)
    now = dt.datetime.fromisoformat(clock)
    lib = telegram.Librarian(bot, client, explain="Simplified Chinese", now=lambda: now)
    lib.handle({"update_id": 1, "message": {"chat": {"id": 7}, "text": f"/start {lib.pairing_code()}"}})
    bot.sent.clear()
    return lib, bot


def _wait(lib):
    for job in list(lib.jobs):
        job.join(10)
    for job in list(lib.jobs):
        job.join(10)


def test_a_book_sent_in_telegram_goes_on_the_shelf_and_its_first_part_is_prepared(home, tmp_path):
    epub = make_epub(tmp_path / "novel.epub", [(f"Chapter {n}", sentences("one", 8, size=1500)) for n in (1, 2, 3)])
    lib, bot = _librarian(home, {"b1": epub.read_bytes()}, FakeClient(kind="fiction", mode="text"))
    lib.handle({"update_id": 2, "message": {"chat": {"id": 7}, "document": {"file_id": "b1", "file_name": "novel.epub"}}})
    _wait(lib)
    text = "\n".join(bot.sent)
    assert "A Test Book" in text and "读原文" in text and "/mode" in text
    assert "没有标准答案" in text and "前情提要" not in text          # the first part: nothing to recall
    assert library.next_unread() is not None and books.current().title == "A Test Book"

    bot.sent.clear()
    lib.handle({"update_id": 3, "message": {"chat": {"id": 7}, "text": "/mode 精华"}})
    _wait(lib)
    assert books.current().mode == "excerpts"
    assert books.book_of(library.next_unread())["mode"] == "excerpts"

    lib.handle({"update_id": 4, "message": {"chat": {"id": 7}, "text": "/books"}})
    assert "A Test Book" in bot.sent[-1]
    lib.handle({"update_id": 5, "message": {"chat": {"id": 7}, "text": "/book pause"}})
    assert books.current() is None


def test_the_daily_round_continues_the_open_book(home, tmp_path):
    import datetime as dt

    epub = make_epub(tmp_path / "novel.epub", [(f"Chapter {n}", sentences("one", 8, size=1500)) for n in (1, 2, 3)])
    client = FakeClient(kind="fiction", mode="text")
    lib, bot = _librarian(home, {}, client)
    book = books.add(epub, client=client)
    finish(books.prepare_next(client, book))                   # the first part is read
    lib._choose_and_prepare("晚上好。", "", dt.datetime(2026, 10, 9, 21, tzinfo=dt.UTC), dt.datetime(2026, 10, 9, 22, tzinfo=dt.UTC))
    assert "接着读《A Test Book》" in bot.sent[-1]
    assert books.book_of(library.next_unread())["segments"][0][0] == 1


def test_a_long_paper_stays_an_article_and_asbook_makes_it_a_book(home, tmp_path):
    paper = tmp_path / "paper.txt"
    paper.write_text("\n\n".join(f"{t}\n\n" + "\n\n".join(["Results were measured carefully in every trial. " * 30] * 12)
                                 for t in ["Introduction", "Methods", "Results", "Discussion"]), encoding="utf-8")
    assert not books.looks_like_book(paper)
    novel = tmp_path / "novel.txt"
    novel.write_text("\n\n".join(f"Chapter {n}\n\n" + "\n\n".join(["She walked on and on. " * 60] * 12)
                                 for n in range(1, 6)), encoding="utf-8")
    assert books.looks_like_book(novel)

    lib, bot = _librarian(home, {"p": paper.read_bytes()}, FakeClient(kind="nonfiction", mode="digest"))
    prepared = []
    lib.start_prepare = lambda article, **_: prepared.append(article)
    lib.handle({"update_id": 2, "message": {"chat": {"id": 7}, "document": {"file_id": "p", "file_name": "paper.txt"}}})
    assert prepared and books.shelf() == []
    lib.handle({"update_id": 3, "message": {"chat": {"id": 7}, "text": "/asbook"}})
    _wait(lib)
    assert books.shelf() and books.current().data["file_name"] == "paper.txt"


def test_a_text_session_plays_through_quietly_answers_a_question_and_ends(home, tmp_path):
    """The player walks the paced steps (no voice), takes a question during a pause, and the open
    question at the end is answered and recorded."""
    import time

    from margin.bus import Bus
    from margin.lesson import Step
    from margin.player import Player
    from test_bibliothecary import QuickVoice

    path = make_epub(tmp_path / "novel.epub", [(f"Chapter {n}", sentences("one", 6, size=600)) for n in (1, 2)])
    client = FakeClient(kind="fiction", mode="text")
    book = books.add(path, client=client)
    folder = books.prepare_next(client, book)
    lesson = Lesson.load(folder / "lesson.json")
    for step in lesson.steps:
        step.pause = min(step.pause, 0.05)
    focused, events, asked = [], [], []
    bus = Bus()
    bus.publish = (lambda publish: lambda kind, **data: (focused.append(data["sentence"]) if kind == "focus" else None,
                                                         publish(kind, **data))[1])(bus.publish)

    def answerer(lesson_, question, current, position=None, history=None, review=None):
        asked.append((question, review))
        return {"steps": [Step(say="Answered.")], "then": "continue"}

    player = Player(bus, QuickVoice(), answerer, record=lambda kind, **data: events.append((kind, data)))
    player.load(lesson)
    player.play()
    end = time.time() + 5
    while time.time() < end and "p3.s1" not in focused:
        time.sleep(0.01)
    player.ask("what does this word mean?")
    while time.time() < end and not player.review:
        time.sleep(0.01)
    assert player.review and player.review["expect"].startswith(brain.OPEN)
    player.ask("I noticed the ending.")
    while time.time() < end and not (events and events[-1][0] == "end"):
        time.sleep(0.01)
    assert events[-1][0] == "end"
    assert {f"p{n}.s1" for n in range(1, len(lesson.paragraphs) + 1)} <= set(focused)   # every paragraph reached
    assert asked[0] == ("what does this word mean?", None) and asked[1][1]["expect"].startswith(brain.OPEN)


def test_up_next_is_the_open_books_part_not_a_paused_books(home, tmp_path):
    client = FakeClient(kind="fiction", mode="text")
    first = books.add(make_epub(tmp_path / "a.epub", [("Chapter 1", sentences("one", 6))]), client=client)
    a = books.prepare_next(client, first)
    books.set_status(first, "paused")
    other = tmp_path / "b.epub"
    make_epub(other, [("Chapter 1", sentences("two", 6))])
    second = books.add(other, client=client)
    b = books.prepare_next(client, second)
    assert library.next_unread() == a                     # the oldest unread
    assert books.up_next() == b                           # but the open book comes first
    books.set_status(second, "paused")
    assert books.up_next() is None                        # both paused: nothing is pushed
