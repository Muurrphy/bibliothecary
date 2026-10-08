"""Stable, renderer-independent contracts for audible and visible speech."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


def _unit(value: float, name: str) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {value}")
    return value


@dataclass(frozen=True)
class AlignmentSpan:
    """A character or token aligned to the generated audio clock."""

    token: str
    start_ms: float
    duration_ms: float
    language: str = "und"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.duration_ms < 0:
            raise ValueError("alignment time must be non-negative")
        _unit(self.confidence, "confidence")


@dataclass(frozen=True)
class Articulation:
    """Continuous mouth motion independent of a rig or visual style.

    The first five channels are sufficient for small displays. The additional
    channels preserve information needed by higher-DOF avatars and soft mouths.
    """

    jaw_open: float
    lip_separation: float
    mouth_width: float
    lip_round: float
    lip_press: float
    lip_protrusion: float = 0.0
    lower_lip_tuck: float = 0.0
    asymmetry: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "jaw_open",
            "lip_separation",
            "mouth_width",
            "lip_round",
            "lip_press",
            "lip_protrusion",
            "lower_lip_tuck",
        ):
            _unit(getattr(self, name), name)
        if not -1.0 <= float(self.asymmetry) <= 1.0:
            raise ValueError("asymmetry must be between -1 and 1")

    def to_dict(self) -> dict[str, float]:
        return {key: float(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class ArticulationEvent:
    """A timed articulation target consumed by displays or physical rigs."""

    session_id: str
    start_ms: float
    duration_ms: float
    viseme: str
    articulation: Articulation
    intensity: float = 1.0
    language: str = "und"
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id or not self.viseme:
            raise ValueError("session_id and viseme must not be empty")
        if self.start_ms < 0 or self.duration_ms < 0:
            raise ValueError("event time must be non-negative")
        _unit(self.intensity, "intensity")
        _unit(self.confidence, "confidence")

    def to_dict(self) -> dict[str, Any]:
        start = round(float(self.start_ms), 3)
        end = round(float(self.start_ms + self.duration_ms), 3)
        return {
            "schema": "robot-lipsync/articulation-event/v1",
            "session_id": self.session_id,
            "start_ms": start,
            "duration_ms": round(end - start, 3),
            "viseme": self.viseme,
            "articulation": self.articulation.to_dict(),
            "intensity": float(self.intensity),
            "language": self.language,
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlaybackEvent:
    """A physical playback-clock event, not merely a network arrival time."""

    session_id: str
    kind: str
    host_monotonic: float
    sample_index: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id or not self.kind:
            raise ValueError("session_id and kind must not be empty")
        if self.host_monotonic < 0 or self.sample_index < 0:
            raise ValueError("playback time must be non-negative")
