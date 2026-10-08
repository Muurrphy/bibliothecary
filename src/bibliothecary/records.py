"""Circulation records: everything said over a reading, kept as it happened.

The player calls ``Ledger.record`` (see ``margin.player.Recorder``). Each event is
appended to ``session.jsonl`` and flushed at once, so a crash or a closed laptop
loses nothing already said. The report is rewritten when the session ends.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Callable
from pathlib import Path

from margin.lesson import Lesson

from . import report


class Ledger:
    def __init__(self, folder: Path, lesson: Lesson, *, client=None,
                 log: Callable[[str], None] | None = None) -> None:
        self.folder, self.lesson, self.client = Path(folder), lesson, client
        self._log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._writer: threading.Thread | None = None
        self._dirty = False

    def record(self, kind: str, **data) -> None:
        if kind == "start":
            data = {"title": data["lesson"].title}
        elif kind == "exchange" and data.get("focus"):
            try:
                data["sentence"] = self.lesson.sentence(data["focus"])
            except KeyError:
                pass
        event = {"t": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "kind": kind,
                 **{k: v for k, v in data.items() if v is not None}}
        with self._lock:
            with open(self.folder / "session.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._dirty = kind != "start"
        if kind == "end":
            self._write_report_later()

    def _write_report_later(self) -> None:
        """The report is written at once; a model's summary (slow) is added in the background."""
        self._write(summarize=False)
        if self.client is not None:
            self._writer = threading.Thread(target=self._write, kwargs={"summarize": True}, daemon=True,
                                            name="bibliothecary-report")
            self._writer.start()

    def _write(self, summarize: bool) -> None:
        try:
            path = report.write(self.folder, client=self.client if summarize else None)
            self._dirty = False
            self._log(f"reading report → {path}")
        except Exception as err:
            self._log(f"could not write the reading report: {err}")

    def close(self) -> None:
        """On the way out (Ctrl-C): finish the report, even for a session that did not reach the end."""
        if self._writer is not None:
            self._writer.join(timeout=60)
        if self._dirty:
            self._write(summarize=self.client is not None)
