"""Where the librarian keeps things: one folder per reading, all on this computer.

    ~/Bibliothecary/                      (or $BIBLIOTHECARY_HOME)
      readings/
        2026-10-08-how-octopuses-sleep/
          lesson.json                     what Margin reads aloud: preview, reading, review
          session.jsonl                   every question and answer, verbatim, as it happened
          summary.json                    what a model made of the session (optional)
          report.md                       the reading report, rewritten from the files above

A real librarian never discloses what you borrowed, so none of this leaves the machine
except the pieces a model or voice service needs for one request.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from margin.lesson import Lesson


def today() -> dt.date:
    return dt.datetime.now().astimezone().date()       # the reader's own calendar day


def home() -> Path:
    return Path(os.environ.get("BIBLIOTHECARY_HOME") or Path.home() / "Bibliothecary").expanduser()


def readings_dir() -> Path:
    return home() / "readings"


def slug(title: str, size: int = 40) -> str:
    """A folder-friendly version of a title; Chinese characters are kept as they are."""
    words = re.findall(r"\w+", title.lower())
    text = "-".join(words)[:size].strip("-")
    return text or "reading"


def new_reading(lesson: Lesson, day: dt.date | None = None) -> Path:
    """A fresh folder for a lesson, named after the day and the title."""
    base = readings_dir() / f"{(day or today()).isoformat()}-{slug(lesson.title)}"
    folder, n = base, 2
    while folder.exists():
        folder, n = base.with_name(f"{base.name}-{n}"), n + 1
    folder.mkdir(parents=True)
    lesson.save(folder / "lesson.json")
    from .store import Store
    Store().put("lesson", folder.name, lesson.to_dict())
    return folder


def readings() -> list[Path]:
    """Every reading folder, oldest first."""
    root = readings_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / "lesson.json").is_file())


def events(folder: Path) -> list[dict]:
    """The session log; a line cut off by a crash is skipped, the rest is kept."""
    from .store import Store
    store = Store()
    stored = store.events(folder.name)
    if stored: return stored
    path = folder / "session.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    for n, event in enumerate(out):
        store.append(folder.name, event, f"readings/{folder.name}/session.jsonl:{n}")
    return out


def status(folder: Path) -> str:
    """"prepared" (not opened yet), "started" (opened, not finished) or "read"."""
    kinds = {e.get("kind") for e in events(folder)}
    if "end" in kinds:
        return "read"
    return "started" if kinds else "prepared"


def next_unread() -> Path | None:
    """The oldest reading not finished yet: what tonight's session opens by default."""
    for folder in readings():
        if status(folder) != "read":
            return folder
    return None


def latest() -> Path | None:
    found = readings()
    return found[-1] if found else None
