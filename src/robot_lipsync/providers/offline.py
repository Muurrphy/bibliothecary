"""Deterministic, no-key alignment fixtures for demos and CI."""

from __future__ import annotations

import json
from pathlib import Path

from ..events import AlignmentSpan


def load_alignment(path: str | Path) -> tuple[str, list[AlignmentSpan]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    language = data.get("language", "und")
    spans = [
        AlignmentSpan(
            token=item["token"],
            start_ms=float(item["start_ms"]),
            duration_ms=float(item["duration_ms"]),
            language=item.get("language", language),
            confidence=float(item.get("confidence", 1.0)),
        )
        for item in data["spans"]
    ]
    return data.get("text", ""), spans


def synthetic_alignment(text: str, *, char_ms: float = 72.0, language: str = "en") -> list[AlignmentSpan]:
    """Create deterministic timing for visualization, never for evaluation."""

    cursor = 0.0
    spans: list[AlignmentSpan] = []
    for character in text:
        if "\u4e00" <= character <= "\u9fff":
            # One Han character is a whole syllable (~200-250 ms in natural
            # Mandarin), not one letter; letter-rate timing made Chinese demos
            # flicker through shapes three times too fast.
            duration = char_ms * 3.0
        elif character in "，。！？、；：":
            duration = char_ms * 2.0
        else:
            duration = char_ms * (0.45 if character.isspace() else (0.70 if character in ".,!?" else 1.0))
        spans.append(AlignmentSpan(character, cursor, duration, language))
        cursor += duration
    return spans
