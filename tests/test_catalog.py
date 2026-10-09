"""The library's own books: the list, fetching from the three clean sources, and the sample."""

import json

import pytest

from bibliothecary import bookfile, books, catalog
from test_books import FakeClient, make_epub, sentences


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_HOME", str(tmp_path / "lib"))
    return tmp_path / "lib"


def test_every_catalog_entry_is_complete_and_from_a_clean_source(home):
    found = catalog.entries()
    assert len(found) >= 20
    assert len({b["id"] for b in found}) == len(found)
    for b in found:
        assert b["source"] in catalog.SOURCES and b["ref"]
        assert b["shelf"] in catalog.SHELVES and b.get("mode") in books.MODES
        assert b["title"] and b["author"] and b.get("why") and b.get("why_zh") and b.get("title_zh")


def test_the_sample_book_is_shipped_and_shelves_without_fetching(home, monkeypatch):
    monkeypatch.setattr(catalog, "_open", lambda *a, **k: pytest.fail("no network for the sample"))
    book = catalog.get(None, "sample", explain="Simplified Chinese")
    assert book.title == "论生命之短暂" and book.mode == "text" and len(book.chapters) == 20
    assert book.chapter(0)[0].startswith("The greater part of mankind, my Paulinus")
    assert "standardebooks.org" in book.data["source"]
    assert catalog.get(None, "sample").folder == book.folder              # once on the shelf, kept
    parsed = bookfile.parse(catalog.SAMPLE)
    text = " ".join(p for c in parsed.chapters for p in c.paragraphs)
    assert "Standard Ebooks" not in text and "73" not in text.split()      # no credits or note numbers in the text


def test_a_gutenberg_book_is_fetched_once_and_shelved(home, tmp_path, monkeypatch):
    epub = make_epub(tmp_path / "x.epub", [("Chapter One", sentences("one", 6))], gutenberg=True).read_bytes()
    calls = []

    def fake_open(url, timeout=60):
        calls.append(url)
        return epub, "application/epub+zip"

    monkeypatch.setattr(catalog, "_open", fake_open)
    book = catalog.get(FakeClient(), "darwin-emotions")
    assert calls == ["https://www.gutenberg.org/ebooks/1227.epub3.images"]
    assert book.data["catalog"] == "darwin-emotions" and book.mode == "digest"
    assert book.data["source"] == "https://www.gutenberg.org/ebooks/1227"
    assert "Gutenberg" not in " ".join(book.chapter(0))
    catalog.get(FakeClient(), "darwin-emotions")
    assert len(calls) == 1


def test_standard_ebooks_downloads_the_plain_epub(home, tmp_path, monkeypatch):
    epub = make_epub(tmp_path / "x.epub", [("Walden", sentences("pond", 6))]).read_bytes()
    page = ('<a href="/ebooks/henry-david-thoreau/walden/downloads/henry-david-thoreau_walden.kepub.epub">k</a>'
            '<a href="/ebooks/henry-david-thoreau/walden/downloads/henry-david-thoreau_walden.epub">e</a>').encode()
    calls = []

    def fake_open(url, timeout=60):
        calls.append(url)
        return (page, "text/html") if url.endswith("/walden") else (epub, "application/epub+zip")

    monkeypatch.setattr(catalog, "_open", fake_open)
    catalog.get(None, "thoreau-walden")
    assert calls[-1] == ("https://standardebooks.org/ebooks/henry-david-thoreau/walden/downloads/"
                         "henry-david-thoreau_walden.epub?source=download")


def test_wikisource_pages_are_assembled_into_an_epub(home, monkeypatch):
    markup = ('<div class="mw-heading mw-heading2"><h2 id="a">卷上</h2></div>'
              '<h3>一 詞以境界爲最上</h3><p>詞以境界爲最上。有境界則自成髙格，自有名句。<sup>①</sup></p>'
              '<table><tr><td>編者的註</td></tr></table>'
              + "".join(f"<p>{'第二段，論詞的文字。' * 12}</p>" for _ in range(3))
              + '<h2>卷下</h2>' + "".join(f"<p>{'卷下的文字，論詞。' * 12}</p>" for _ in range(3)))

    def fake_open(url, timeout=60):
        return json.dumps({"parse": {"text": markup, "links": []}}).encode(), "application/json"

    monkeypatch.setattr(catalog, "_open", fake_open)
    book = catalog.get(None, "wang-guowei-renjian-cihua", explain="Simplified Chinese")
    assert [c["title"] for c in book.chapters] == ["卷上", "卷下"]
    first = book.chapter(0)
    assert first[0] == "一 詞以境界爲最上" and first[1].endswith("自有名句。")     # footnote marker gone
    assert not any("編者" in p for p in first) and book.lang == "zh"


def test_a_bare_number_takes_the_title_from_the_first_line(tmp_path):
    path = make_epub(tmp_path / "s.epub", [("IX.", ["ON A PIECE OF CHALK."] + sentences("chalk", 6))])
    parsed = bookfile.parse(path)
    assert parsed.chapters[0].title == "IX. ON A PIECE OF CHALK."


def test_telegram_lists_the_library_and_gets_the_sample(home):
    from test_books import _librarian, _wait

    lib, bot = _librarian(home, {}, FakeClient(kind="essays", mode="text"))
    lib.handle({"update_id": 2, "message": {"chat": {"id": 7}, "text": "/library"}})
    assert "darwin-emotions" in bot.sent[-1] and "生命与心智" in bot.sent[-1] and "/get sample" in bot.sent[-1]
    lib.handle({"update_id": 3, "message": {"chat": {"id": 7}, "text": "/get sample"}})
    _wait(lib)
    text = "\n".join(bot.sent)
    assert "论生命之短暂" in text and "读原文" in text
    assert books.current().data["catalog"] == "sample-seneca"
