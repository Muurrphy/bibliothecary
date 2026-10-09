"""Circulation records: everything said over a reading, kept as it happened.

The player calls ``Ledger.record`` (see ``margin.player.Recorder``). Each event is
appended to ``session.jsonl`` and flushed at once, so a crash or a closed laptop
loses nothing already said. The report is rewritten when the session ends.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from margin.lesson import Lesson

from . import report, safe


class Ledger:
    def __init__(self, folder: Path, lesson: Lesson, *, client=None,
                 log: Callable[[str], None] | None = None) -> None:
        self.folder, self.lesson, self.client = Path(folder), lesson, client
        self._log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._writer: threading.Thread | None = None
        self._dirty = False
        self._revision = 0
        self._closed = False
        from .store import Store
        self.store = Store()

    def restore(self) -> dict:
        return self.store.get("checkpoint", self.folder.name) or safe.read_json(self.folder / "checkpoint.json")

    def checkpoint(self, data: dict) -> None:
        self.store.put("checkpoint", self.folder.name, data)
        safe.write_json(self.folder / "checkpoint.json", data)

    def record(self, kind: str, **data) -> None:
        origin = data.pop('_origin', None)
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
            self._revision += 1
            self.store.append(self.folder.name, event, origin=origin)
            self.store.export_events(self.folder.name, self.folder / "session.jsonl")
            self._dirty = self._dirty or kind != "start"     # a late "start" must not hide what came before
        if kind in ("utterance", "companion", "exchange", "reader_action"):
            self.store.put("organization_pending", self.folder.name, {"pending": True, "at": event["t"]})
        if kind == "exchange":
            from .learning import observe
            observe(self.store, self.folder.name, event)
        if kind == "end":
            self._write_report_later()

    def capture_utterance(self, channel, focus):
        """Bind incoming speech to this reading before transcription or a book switch.

        No audio is saved. ASR output is never rewritten by the note organizer.
        Even interrupted, unanswered and echo-candidate turns remain inspectable.
        """
        key = uuid.uuid4().hex
        started = dt.datetime.now().astimezone().isoformat(timespec='seconds')
        self.record('utterance_pending', turn=key, channel=channel, focus=focus)
        def captured(text, status='received'):
            self.record('utterance', turn=key, text=text, who='reader', focus=focus,
                        channel=channel, transcription='unverified' if channel=='voice' else 'typed',
                        status=status, started=started, _origin='utterance:'+key)
            # The ASR can finish after the reader has already closed/switched sessions.
            if self._closed:
                self._write_report_later()
        return captured

    def companion(self, text, focus, kind, interrupted=False):
        self.record('companion', who='librarian', text=text, focus=focus,
                    role=kind, playback='interrupted_or_failed' if interrupted else 'completed')

    def _write_report_later(self) -> None:
        """The report is written at once; a model's summary (slow) is added in the background."""
        self._write(summarize=False)
        if self.client is not None:
            self._writer = threading.Thread(target=self._write, kwargs={"summarize": True}, daemon=True,
                                            name="bibliothecary-report")
            self._writer.start()

    def _write(self, summarize: bool) -> None:
        try:
            with self._lock: revision = self._revision
            path = report.write(self.folder, client=self.client if summarize else None)
            with self._lock:
                self._dirty = self._revision != revision
            self._log(f"reading report → {path}")
        except Exception as err:
            self._log(f"could not write the reading report: {err}")

    def close(self) -> None:
        """On the way out (Ctrl-C): finish the report, even for a session that did not reach the end."""
        self._closed = True
        if self._writer is not None:
            self._writer.join(timeout=60)
        if self._dirty:
            self._write(summarize=False)
            if self.client is not None: self._write(summarize=True)
