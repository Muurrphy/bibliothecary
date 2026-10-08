"""The reading room, kept open for the librarian: any reading can be opened by name.

``biblio telegram`` runs one, so a link in the chat opens tonight's reading straight on the
phone (or the Kindle shows whatever is open). It serves only this computer's local network:
each reader runs their own librarian, and nobody else can reach it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from margin import cli as margin_cli
from margin.lesson import Lesson

from . import library, report
from .records import Ledger


class ReadingRoom:
    def __init__(self, args, client=None, *, log: Callable[[str], None] | None = None, start=margin_cli.start) -> None:
        self.client, self.log = client, log or (lambda _msg: None)
        self.room = start(None, args, client=client)
        self.room.app.opener = self.open
        self.folder: Path | None = None
        self.ledger: Ledger | None = None
        self._lock = threading.Lock()

    @property
    def kindle(self) -> str:
        return self.room.urls["kindle"]

    def link(self, folder: Path) -> str:
        """Opening this on the phone opens the reading there."""
        return f"{self.room.urls['base']}/open/{quote(folder.name)}"

    def open(self, name: str) -> bool:
        folder = library.readings_dir() / Path(name).name          # a name, never a path
        if not (folder / "lesson.json").is_file():
            return False
        with self._lock:
            if folder == self.folder:
                return True                                          # already open: leave it as it is
            previous, self.ledger = self.ledger, None
            if previous is not None:                                 # file the last one without making anyone wait
                threading.Thread(target=previous.close, daemon=True, name="bibliothecary-file").start()
            lesson = Lesson.load(folder / "lesson.json")
            if not (folder / "report.md").exists():
                report.write(folder)
            self.ledger = Ledger(folder, lesson, client=self.client, log=self.log)
            self.room.player.set_recorder(self.ledger.record)
            self.room.player.load(lesson)
            self.folder = folder
        self.log(f"reading room: {lesson.title}")
        return True

    def close(self) -> None:
        if self.ledger is not None:
            self.ledger.close()
        self.room.close()
