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
        self._emitted_prefix: list[tuple] = []

    @staticmethod
    def _event_identity(event: ArticulationEvent) -> tuple:
        articulation = event.articulation
        return (
            round(event.start_ms, 6),
            round(event.duration_ms, 6),
            event.viseme,
            event.language,
            tuple(round(value, 6) for value in articulation.to_dict().values()),
            event.metadata.get("phoneme"),
            event.metadata.get("tone"),
        )

    def append(self, spans: list[AlignmentSpan], *, final: bool = False) -> list[ArticulationEvent]:
        self.alignment.append(spans)
        if final:
            self.alignment.finish()
        stable = self.alignment.stable_snapshot()
        planning = self.alignment.planning_snapshot()
        events = phonemes_to_articulation(
            self.session_id,
            alignment_to_phonemes(planning),
            visual_lead_ms=self.visual_lead_ms,
        )
        if final:
            safe_end = len(events)
        elif len(planning) > len(stable):
            cutoff_ms = planning[len(stable)].start_ms
            safe_end = sum(float(event.metadata.get("audio_start_ms", event.start_ms)) < cutoff_ms for event in events)
        else:
            safe_end = max(0, len(events) - 1)
        if safe_end < self._emitted:
            raise RuntimeError("stable articulation prefix shrank")
        prefix = [self._event_identity(event) for event in events[: self._emitted]]
        if prefix != self._emitted_prefix:
            raise RuntimeError("provider or language front end rewrote an emitted articulation prefix")
        new = events[self._emitted : safe_end]
        self._emitted_prefix.extend(self._event_identity(event) for event in new)
        self._emitted = safe_end
        return new

    def finish(self) -> list[ArticulationEvent]:
        return self.append([], final=True)
