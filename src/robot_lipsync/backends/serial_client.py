"""Small synchronous control-plane client for the reference firmware.

Live audio code should call ``append(..., confirm=False)`` so it never blocks on
display acknowledgements. Reset/start/count are control-plane operations.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import BinaryIO

from ..events import ArticulationEvent
from .serial_v1 import LipReply, encode_count, encode_end, encode_event, encode_reset, encode_start, parse_reply


class SerialTimelineClient:
    def __init__(self, stream: BinaryIO, *, timeout_s: float = 1.0) -> None:
        self.stream = stream
        self.timeout_s = timeout_s

    def _write(self, payload: bytes) -> None:
        self.stream.write(payload)
        flush = getattr(self.stream, "flush", None)
        if flush:
            flush()

    def wait_for(self, name: str) -> LipReply:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            line = self.stream.readline()
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            reply = parse_reply(line)
            if reply is None:
                continue
            if reply.level == "ERR":
                raise RuntimeError(f"lip device rejected {reply.name}: {reply.fields}")
            if reply.name == name:
                return reply
        raise TimeoutError(f"timed out waiting for LIP/{name}")

    def reset(self, session_id: str) -> int:
        self._write(encode_reset(session_id))
        reply = self.wait_for("RESET")
        return int(reply.fields["capacity"])

    def append(self, events: Iterable[ArticulationEvent], *, confirm: bool = False) -> int:
        count = 0
        for event in events:
            self._write(encode_event(event))
            count += 1
        if confirm and count:
            return self.count(event.session_id)
        return count

    def count(self, session_id: str) -> int:
        self._write(encode_count(session_id))
        return int(self.wait_for("COUNT").fields["events"])

    def start(self, session_id: str, *, delay_ms: int = 0, offset_ms: int = 0) -> LipReply:
        self._write(encode_start(session_id, delay_ms=delay_ms, offset_ms=offset_ms))
        return self.wait_for("START")

    def end(self, session_id: str) -> LipReply:
        self._write(encode_end(session_id))
        return self.wait_for("END")
