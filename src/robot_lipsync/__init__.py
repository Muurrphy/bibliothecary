"""Real-time, muscle-aware lip sync for constrained embodied agents."""

from .events import AlignmentSpan, Articulation, ArticulationEvent, PlaybackEvent
from .metrics import LatencyTrace, summarize_traces
from .phonemes import AlignmentBuffer, TimedPhoneme, alignment_to_phonemes, spans_from_elevenlabs
from .planner import enforce_constraints, phonemes_to_articulation
from .streaming import IncrementalArticulationCompiler

__all__ = [
    "AlignmentBuffer",
    "AlignmentSpan",
    "Articulation",
    "ArticulationEvent",
    "LatencyTrace",
    "IncrementalArticulationCompiler",
    "PlaybackEvent",
    "TimedPhoneme",
    "alignment_to_phonemes",
    "enforce_constraints",
    "phonemes_to_articulation",
    "spans_from_elevenlabs",
    "summarize_traces",
]

__version__ = "0.1.0"
