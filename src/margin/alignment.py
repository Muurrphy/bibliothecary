"""Local waveform checks for provider character timing; not speech recognition.

Only unambiguous phrase/pause matches are adjusted. Ambiguous recordings keep
their provider timing and report that limitation. No network or model is used.
"""
from __future__ import annotations

import math
import re

FIELDS = ('characters', 'character_start_times_seconds', 'character_end_times_seconds')
BREAKS = re.compile(r'[，。！？；：,.!?;:]')
SPOKEN = re.compile(r'\w', re.UNICODE)


def valid_alignment(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    chars, starts, ends = (value.get(k) for k in FIELDS)
    if not all(isinstance(v, (list, tuple)) for v in (chars, starts, ends)):
        return False
    if not chars or not len(chars) == len(starts) == len(ends):
        return False
    if not all(isinstance(c, str) and c for c in chars):
        return False
    if not all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t)
               for t in (*starts, *ends)):
        return False
    return all(0 <= a <= b for a, b in zip(starts, ends)) and all(
        a <= b for a, b in zip(starts, starts[1:]))


def speech_windows(samples: list[int], rate: int) -> list[list[float]]:
    """10 ms PCM activity with 80 ms gaps bridged, and 20 ms edge padding."""
    if not samples or rate <= 0:
        return []
    hop = max(1, round(rate * .01))
    levels = []
    for i in range(0, len(samples), hop):
        chunk = samples[i:i+hop:4]
        levels.append(math.sqrt(sum(float(v)*v for v in chunk) / len(chunk)))
    loud = sorted(levels)[min(len(levels)-1, int(len(levels)*.8))]
    threshold = max(60., loud * .06)
    runs, start = [], None
    for i, on in enumerate([v > threshold for v in levels] + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if runs and start-runs[-1][1] <= 8:
                runs[-1][1] = i
            else:
                runs.append([start, i])
            start = None
    duration = len(samples) / rate
    step = hop / rate
    return [[max(0, a*step-.02), min(duration, b*step+.02)]
            for a, b in runs if (b-a)*step >= .04]


def reconcile(alignment: dict | None, windows: list[list[float]], duration: float) -> tuple[dict | None, str]:
    """Bound speech to its recording, then anchor clearly matched phrase edges.

    Character timing inside a phrase is rescaled, not re-recognised. This does
    not claim phoneme-accurate alignment, and never shifts an entire recording
    by an arbitrary fixed offset.
    """
    if not valid_alignment(alignment):
        return None, 'unavailable'
    chars, starts, ends = (list(alignment[k]) for k in FIELDS)
    if not windows:
        return None, 'silent'
    # Invalid timing outside the recording must not animate unrelated audio.
    if any(a > duration+.05 for c, a in zip(chars, starts) if SPOKEN.search(c)):
        return None, 'outside_audio'
    starts = [min(duration, t) for t in starts]
    ends = [min(duration, t) for t in ends]
    groups, group = [], []
    for i, c in enumerate(chars):
        if SPOKEN.search(c):
            group.append(i)
        if BREAKS.search(c) and group:
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    corrected = 0
    if len(groups) == len(windows):
        for indices, (a, b) in zip(groups, windows):
            first, last = indices[0], indices[-1]
            old_a, old_b = starts[first], ends[last]
            length = old_b-old_a
            if length <= 0:
                continue
            ratio = (b-a)/length
            # Noise and missing/extra pauses should not silently relabel words.
            if max(abs(a-old_a), abs(b-old_b)) > .45 or not .5 <= ratio <= 2.5:
                continue
            for i in indices:
                starts[i] = a+(starts[i]-old_a)*ratio
                ends[i] = a+(ends[i]-old_a)*ratio
            corrected += 1
    # Bound overlapping provider characters before splitting them into phones.
    spoken = [i for i, c in enumerate(chars) if SPOKEN.search(c)]
    if not spoken:
        return None, 'unavailable'
    for i, j in zip(spoken, spoken[1:]):
        ends[i] = max(starts[i], min(ends[i], starts[j]))
    # Punctuation separates pronunciation contexts but has no mouth event.
    previous = 0.
    for i, c in enumerate(chars):
        if not SPOKEN.search(c):
            starts[i] = ends[i] = previous
        else:
            previous = ends[i]
    result = dict(zip(FIELDS, (chars, starts, ends)))
    if not valid_alignment(result):
        return None, 'invalid_after_waveform_check'
    status = 'waveform_phrase_edges' if corrected == len(groups) else (
        'waveform_partial_edges' if corrected else 'provider_unverified')
    return result, status
