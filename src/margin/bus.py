"""The channel between the computer and the e-reader.

The e-reader cannot be pushed to directly, so it asks: "anything after event
N?". The question is held open until something happens (long-polling), which
works in the most limited e-reader browsers and costs nothing while idle.

Besides the event log, the bus keeps a *screen*: the reduced state of what the
e-reader should currently show. A reader that reloads (old Kindle browsers run
out of memory and restart) asks for the screen and carries on from there.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any

MAX_EVENTS = 500


def empty_screen() -> dict[str, Any]:
    return {
        "lesson": None,     # {"title", "source", "paragraphs": [{"id", "sentences": [{"id", "text"}]}]}
        "focus": None,      # sentence id being explained
        "marks": [],        # [{"sentence", "phrase"}] circled words
        "note": None,       # {"text", "sentence"}
        "figure": None,     # {"type", "title", ..., "sentence"} a small diagram
        "caption": "",      # what the companion is saying right now
        "answer": None,     # {"question", "text", "done"}
        "status": "idle",   # idle | reading | paused | waiting (for a review answer) | listening | thinking | answering | done
        "progress": [0, 0],
    }


class Bus:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._first = 0                      # sequence number of _events[0]
        self._cond = threading.Condition()
        self._screen = empty_screen()

    @property
    def seq(self) -> int:
        return self._first + len(self._events)

    def publish(self, kind: str, **data: Any) -> int:
        with self._cond:
            event = {"seq": self.seq + 1, "kind": kind, "data": data, "t": time.time()}
            self._events.append(event)
            if len(self._events) > MAX_EVENTS:
                drop = len(self._events) - MAX_EVENTS
                del self._events[:drop]
                self._first += drop
            _reduce(self._screen, kind, data)
            self._cond.notify_all()
            return event["seq"]

    def screen(self) -> dict[str, Any]:
        with self._cond:
            return {"seq": self.seq, "screen": deepcopy(self._screen)}

    def since(self, seq: int, timeout: float = 20.0) -> dict[str, Any]:
        """Events after ``seq``; waits up to ``timeout`` seconds for one to arrive.

        A reader that fell too far behind (or comes from an older server run)
        is told to reload the whole screen instead."""

        deadline = time.monotonic() + timeout
        with self._cond:
            if seq > self.seq:   # a reader left over from an earlier run of the server
                return {"seq": self.seq, "reset": True, "screen": deepcopy(self._screen)}
            while self.seq <= seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"seq": self.seq, "events": []}
                self._cond.wait(remaining)
            if seq < self._first:
                return {"seq": self.seq, "reset": True, "screen": deepcopy(self._screen)}
            return {"seq": self.seq, "events": deepcopy(self._events[seq - self._first:])}


def _reduce(screen: dict[str, Any], kind: str, data: dict[str, Any]) -> None:
    if kind == "lesson":
        screen.clear()
        screen.update(empty_screen())
        screen["lesson"] = data
        screen["progress"] = [0, data.get("steps", 0)]
    elif kind == "focus":
        screen["focus"] = data.get("sentence")
    elif kind == "mark":
        screen["marks"].append({"sentence": data.get("sentence"), "phrase": data.get("phrase")})
    elif kind == "clear_marks":
        screen["marks"] = []
    elif kind == "note":
        screen["note"] = {"text": data.get("text", ""), "sentence": data.get("sentence")}
    elif kind == "clear_note":
        screen["note"] = None
    elif kind == "figure":
        screen["figure"] = dict(data)
    elif kind == "clear_figure":
        screen["figure"] = None
    elif kind == "caption":
        screen["caption"] = data.get("text", "")
    elif kind == "answer":
        screen["answer"] = {"question": data.get("question", ""), "text": data.get("text", ""), "done": bool(data.get("done"))}
    elif kind == "clear_answer":
        screen["answer"] = None
    elif kind == "status":
        screen["status"] = data.get("state", "idle")
    elif kind == "progress":
        screen["progress"] = [data.get("step", 0), data.get("of", 0)]
