"""Provider contracts. Providers produce audio and alignment, never rig commands."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from ..events import AlignmentSpan


@dataclass(frozen=True)
class AlignedAudioChunk:
    pcm: bytes
    sample_rate: int
    alignment: tuple[AlignmentSpan, ...] = ()
    is_final: bool = False


class AlignedTtsProvider(Protocol):
    def stream(self, text: str, *, trace=None) -> Iterable[AlignedAudioChunk]: ...
