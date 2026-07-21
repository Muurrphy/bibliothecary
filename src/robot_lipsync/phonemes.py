"""Convert incremental character alignment into timed phonemes."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from .events import AlignmentSpan


@dataclass(frozen=True)
class TimedPhoneme:
    symbol: str
    start_ms: float
    duration_ms: float
    language: str
    confidence: float = 1.0


class AlignmentBuffer:
    """A thread-safe, append-only alignment stream.

    While a stream is live, the final incomplete English word is withheld. This
    prevents a partial token from being compiled and sent to immutable hardware.
    """

    def __init__(self) -> None:
        self._spans: list[AlignmentSpan] = []
        self._lock = threading.Lock()
        self._done = threading.Event()

    def append(self, spans: Iterable[AlignmentSpan]) -> None:
        with self._lock:
            self._spans.extend(spans)

    __call__ = append

    def finish(self) -> None:
        self._done.set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def snapshot(self) -> list[AlignmentSpan]:
        with self._lock:
            return list(self._spans)

    def stable_snapshot(self) -> list[AlignmentSpan]:
        spans = self.snapshot()
        if self.done or not spans:
            return spans
        end = len(spans)
        if re.match(r"[A-Za-z']", spans[-1].token):
            while end and re.match(r"[A-Za-z']", spans[end - 1].token):
                end -= 1
        return spans[:end]


def spans_from_elevenlabs(data: Mapping, language: str = "und") -> list[AlignmentSpan]:
    """Parse both WebSocket camelCase and HTTP snake_case alignment."""

    chars = data.get("chars") or data.get("characters") or []
    seconds = "character_start_times_seconds" in data
    starts = data.get("charStartTimesMs") or data.get("character_start_times_seconds") or []
    durations = data.get("charDurationsMs") or data.get("character_durations_seconds") or []
    if not durations and seconds:
        ends = data.get("character_end_times_seconds") or []
        if len(ends) == len(starts):
            durations = [max(0.0, float(end) - float(start)) for start, end in zip(starts, ends, strict=False)]
    if not (len(chars) == len(starts) == len(durations)):
        raise ValueError("alignment arrays must have equal lengths")
    scale = 1000.0 if seconds else 1.0
    return [
        AlignmentSpan(str(char), float(start) * scale, float(duration) * scale, language)
        for char, start, duration in zip(chars, starts, durations, strict=False)
    ]


@lru_cache(maxsize=1)
def _cmu_dictionary():
    try:
        import cmudict  # type: ignore

        return cmudict.dict()
    except ImportError:
        return None


@lru_cache(maxsize=8192)
def english_phones(word: str) -> tuple[str, ...]:
    dictionary = _cmu_dictionary()
    if dictionary:
        pronunciations = dictionary.get(word.lower())
        if pronunciations:
            return tuple(pronunciations[0])

    value = word.lower()
    digraphs = {
        "th": "TH",
        "sh": "SH",
        "ch": "CH",
        "ph": "F",
        "ee": "IY1",
        "oo": "UW1",
        "ou": "AW1",
        "ow": "OW1",
        "ai": "EY1",
        "ay": "EY1",
        "oi": "OY1",
        "oy": "OY1",
    }
    letters = {
        "a": "AE1",
        "e": "EH1",
        "i": "IH1",
        "o": "OW1",
        "u": "UW1",
        "b": "B",
        "c": "K",
        "d": "D",
        "f": "F",
        "g": "G",
        "h": "H",
        "j": "JH",
        "k": "K",
        "l": "L",
        "m": "M",
        "n": "N",
        "p": "P",
        "q": "K",
        "r": "R",
        "s": "S",
        "t": "T",
        "v": "V",
        "w": "W",
        "x": "K",
        "y": "Y",
        "z": "Z",
    }
    result: list[str] = []
    index = 0
    while index < len(value):
        pair = value[index : index + 2]
        if pair in digraphs:
            result.append(digraphs[pair])
            index += 2
        else:
            if value[index] in letters:
                result.append(letters[value[index]])
            index += 1
    return tuple(result or ["AH0"])


def _allocate(symbols: list[str], start_ms: float, duration_ms: float, language: str) -> list[TimedPhoneme]:
    if not symbols:
        return []
    vowel_bases = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
    weights = [2.1 if re.sub(r"[012]$", "", symbol) in vowel_bases else 0.8 for symbol in symbols]
    total = sum(weights)
    cursor = start_ms
    result = []
    for symbol, weight in zip(symbols, weights, strict=False):
        length = duration_ms * weight / total
        result.append(TimedPhoneme(symbol, cursor, length, language))
        cursor += length
    return result


def alignment_to_phonemes(spans: Iterable[AlignmentSpan]) -> list[TimedPhoneme]:
    """Compile English words; preserve unsupported scripts as neutral syllables."""

    spans = list(spans)
    result: list[TimedPhoneme] = []
    index = 0
    while index < len(spans):
        span = spans[index]
        if re.match(r"[A-Za-z']", span.token):
            first = index
            chars: list[str] = []
            while index < len(spans) and re.match(r"[A-Za-z']", spans[index].token):
                chars.append(spans[index].token)
                index += 1
            start = spans[first].start_ms
            end = spans[index - 1].start_ms + spans[index - 1].duration_ms
            result.extend(_allocate(list(english_phones("".join(chars))), start, max(1.0, end - start), "en"))
            continue
        if span.token and "\u3400" <= span.token[0] <= "\u9fff":
            result.append(TimedPhoneme("SYLLABLE", span.start_ms, span.duration_ms, "zh-CN"))
        index += 1
    return result
