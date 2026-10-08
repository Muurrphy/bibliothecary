"""End-of-turn to physical-first-sample latency instrumentation."""

from __future__ import annotations

import json
import math
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field

STANDARD_MARKS = (
    "end_of_user_speech",
    "turn_committed",
    "llm_first_token",
    "phrase_committed",
    "tts_request_start",
    "tts_response_headers",
    "tts_first_audio",
    "device_first_audio_chunk",
    "physical_audio_start",
    "first_visible_motion",
)


@dataclass
class LatencyTrace:
    origin: float = field(default_factory=time.monotonic)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    marks: dict[str, float] = field(default_factory=dict)
    counters: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    def mark(self, name: str, at: float | None = None, *, once: bool = True) -> float:
        if not name:
            raise ValueError("metric name must not be empty")
        value = time.monotonic() if at is None else float(at)
        with self._lock:
            if once and name in self.marks:
                return self.marks[name]
            self.marks[name] = value
        return value

    def count(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0.0) + float(value)

    def elapsed_ms(self, name: str, since: str | None = None) -> float | None:
        with self._lock:
            end = self.marks.get(name)
            start = self.origin if since is None else self.marks.get(since)
        return None if end is None or start is None else (end - start) * 1000.0

    def snapshot_ms(self) -> dict[str, float]:
        with self._lock:
            marks = dict(self.marks)
        return {
            name: round((value - self.origin) * 1000.0, 3)
            for name, value in sorted(marks.items(), key=lambda item: item[1])
        }

    def to_dict(self) -> dict:
        return {
            "schema": "robot-lipsync/latency-trace/v1",
            "session_id": self.session_id,
            "milliseconds": self.snapshot_ms(),
            "counters": dict(self.counters),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sequence")
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * probability
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize_traces(records: list[dict], mark: str = "physical_audio_start") -> dict:
    values = [float(record["milliseconds"][mark]) for record in records if mark in record.get("milliseconds", {})]
    if not values:
        raise ValueError(f"no traces contain mark {mark!r}")
    return {
        "mark": mark,
        "samples": len(values),
        "min_ms": min(values),
        "mean_ms": statistics.fmean(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "max_ms": max(values),
    }
