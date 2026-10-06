"""Check word timestamps against the audio they describe.

TTS engines report word timings on their own clock. Some voices run a little
early or late against the audio file they return (edge-tts Spanish voices, for
example, report every word about 90 ms before it is heard; the Mandarin and
English voices about 60 ms). A constant offset like that is invisible in the
data but very visible on a face: the mouth runs ahead of the voice, and in a
fast, syllable-timed language such as Spanish 90 ms is most of a syllable.

``estimate_offset_ms`` compares where the alignment says someone is speaking
with where the audio is actually loud, and returns the shift that makes them
agree best. Pure Python, no numpy.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import replace

from .events import AlignmentSpan

FRAME_MS = 10


def loudness_db(samples: Sequence[float], sample_rate: int, frame_ms: int = FRAME_MS) -> list[float]:
    """RMS loudness per frame, in dB (samples in -1..1)."""

    size = max(1, int(sample_rate * frame_ms / 1000))
    result = []
    for start in range(0, len(samples) - size + 1, size):
        chunk = samples[start : start + size]
        rms = math.sqrt(sum(value * value for value in chunk) / size)
        result.append(20.0 * math.log10(rms + 1e-5))
    return result


def estimate_offset_ms(
    spans: Iterable[AlignmentSpan],
    samples: Sequence[float],
    sample_rate: int,
    *,
    search_ms: int = 200,
    floor_db: float = 35.0,
) -> float:
    """Shift (ms) to add to every span so speech in the alignment lines up with
    loud audio. Positive means the timestamps are early."""

    loud = loudness_db(samples, sample_rate)
    if not loud:
        return 0.0
    threshold = max(loud) - floor_db
    voiced = [value > threshold for value in loud]
    frames = len(voiced)
    speaking = [False] * frames
    for span in spans:
        if not span.token.strip():
            continue
        first = max(0, int(span.start_ms / FRAME_MS))
        last = min(frames, int((span.start_ms + span.duration_ms) / FRAME_MS))
        for index in range(first, last):
            speaking[index] = True

    def agreement(shift: int) -> int:
        return sum(
            1
            for index in range(frames)
            if (speaking[index - shift] if 0 <= index - shift < frames else False) == voiced[index]
        )

    steps = range(-search_ms // FRAME_MS, search_ms // FRAME_MS + 1)
    best = max(steps, key=lambda step: (agreement(step), -abs(step)))
    return float(best * FRAME_MS)


def shift_spans(spans: Iterable[AlignmentSpan], offset_ms: float) -> list[AlignmentSpan]:
    """Move every span by ``offset_ms`` (never before zero)."""

    return [replace(span, start_ms=max(0.0, span.start_ms + offset_ms)) for span in spans]
