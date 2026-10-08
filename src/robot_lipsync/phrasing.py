"""Release a natural first phrase early without cutting unstable tokens."""

from __future__ import annotations

import re

_HARD_END = re.compile(r"([。！？!?…]+[\"'”’）)]*|(?:\.[\"'”’）)]*(?=\s|$)))")
_CLAUSE_END = re.compile(r"[，,；;：:]")
_CJK = re.compile(r"[\u3400-\u9fff]")
_EN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_UNSAFE_EN_ENDINGS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "because",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "nor",
    "not",
    "of",
    "on",
    "or",
    "than",
    "that",
    "the",
    "then",
    "to",
    "unless",
    "until",
    "when",
    "while",
    "with",
    "without",
}


def split_ready_phrases(buffer: str, *, first_phrase: bool = False) -> tuple[list[str], str]:
    """Prefer sentences, then readable clauses, then safe word boundaries."""

    ready: list[str] = []
    while buffer:
        eager = first_phrase and not ready
        hard = _HARD_END.search(buffer)
        clause = _CLAUSE_END.search(buffer)
        cut = hard.end() if hard else None
        if clause and (cut is None or clause.end() < cut):
            candidate = buffer[: clause.end()]
            cjk = len(_CJK.findall(candidate))
            words = len(_EN_WORD.findall(candidate))
            if cjk >= (4 if eager else 6) or words >= (6 if eager else 9):
                cut = clause.end()
        force_length = 48 if eager else 64
        if cut is None and not _CJK.search(buffer) and len(buffer) >= force_length:
            low, high = (30, 43) if eager else (40, 49)
            split_at = buffer.rfind(" ", low, high)
            if split_at > 0:
                cut = split_at + 1
        if cut is None:
            break
        phrase = buffer[:cut].strip()
        buffer = buffer[cut:]
        if len(re.sub(r"\s+", "", phrase)) >= 2:
            ready.append(phrase)
    return ready, buffer


def split_timed_first_phrase(buffer: str, *, min_words: int = 5) -> tuple[list[str], str]:
    """A timeout fuse for unpunctuated English LLM output."""

    if not buffer.strip() or _CJK.search(buffer):
        return [], buffer
    cut = len(buffer) if buffer[-1:].isspace() else buffer.rfind(" ")
    if cut <= 0:
        return [], buffer
    candidate = buffer[:cut].strip()
    words = _EN_WORD.findall(candidate)
    if len(words) < min_words or words[-1].lower() in _UNSAFE_EN_ENDINGS:
        return [], buffer
    return [candidate], buffer[cut:]
