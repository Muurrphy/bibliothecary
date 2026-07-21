"""Causal compilation of growing TTS alignment without rewriting emitted motion."""

from __future__ import annotations

from .events import AlignmentSpan, ArticulationEvent
from .phonemes import AlignmentBuffer, alignment_to_phonemes
from .planner import phonemes_to_articulation


class IncrementalArticulationCompiler:
    """Append alignment chunks and emit only stable, previously unseen events.

    A live stream withholds the incomplete English word and one look-ahead event.
    This gives the coarticulation planner a stable next target while preserving a
    strictly append-only contract suitable for small hardware event queues.
    """

    def __init__(self, session_id: str, *, visual_lead_ms: float = 42.0) -> None:
        self.session_id = session_id
        self.visual_lead_ms = visual_lead_ms
        self.alignment = AlignmentBuffer()
        self._emitted = 0

    def append(self, spans: list[AlignmentSpan], *, final: bool = False) -> list[ArticulationEvent]:
        self.alignment.append(spans)
        if final:
            self.alignment.finish()
        stable = self.alignment.stable_snapshot()
        events = phonemes_to_articulation(
            self.session_id,
            alignment_to_phonemes(stable),
            visual_lead_ms=self.visual_lead_ms,
        )
        safe_end = len(events) if final else max(0, len(events) - 1)
        if safe_end < self._emitted:
            raise RuntimeError("stable articulation prefix shrank")
        new = events[self._emitted : safe_end]
        self._emitted = safe_end
        return new

    def finish(self) -> list[ArticulationEvent]:
        return self.append([], final=True)
