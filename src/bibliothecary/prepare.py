"""Preparing a reading: article → three-part lesson → its own folder with the reading guide."""

from __future__ import annotations

import re
from pathlib import Path

from margin import brain
from margin.ingest import load_article

from . import library, report


def guess_language(text: str) -> str:
    """"zh-CN" when most letters are Chinese characters, else "en"."""
    han = len(re.findall(r"[㐀-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "zh-CN" if han > latin / 3 else "en"


def prepare(client, article: str, *, title: str | None = None, explain: str = "English",
            language: str | None = None, bedtime: bool = False, preview: bool = True,
            review: int = 3, log=None) -> Path:
    """Read the article (URL or file), write the lesson and the reading guide; return the folder."""
    found_title, text, source = load_article(article)
    if len(text.split()) < 40 and len(text) < 200:
        raise ValueError(f"found almost no text at {article}")
    if log:
        log(f"preparing “{title or found_title}” ({len(text.split())} words)…")
    lesson = brain.build_lesson(client, title or found_title, text, explain_language=explain, source=source,
                                language=language or guess_language(text), bedtime=bedtime,
                                preview=preview, review=review)
    if log:
        for issue in lesson.problems():
            log(f"warning: {issue}")
    folder = library.new_reading(lesson)
    report.write(folder)
    return folder
