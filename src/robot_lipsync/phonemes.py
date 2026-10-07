"""Convert incremental character alignment into timed phonemes.

English uses CMUdict when available, Spanish uses a deterministic orthographic
front end, and Mandarin uses pypinyin's phrase-aware readings when the optional
``mandarin`` extra is installed.
"""

from __future__ import annotations

import re
import threading
import unicodedata
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
    tone: int | None = None


_SPANISH_LETTERS = frozenset("abcdefghijklmnñopqrstuvwxyzáéíóúü")
_MANDARIN_INITIALS = (
    "zh",
    "ch",
    "sh",
    "b",
    "p",
    "m",
    "f",
    "d",
    "t",
    "n",
    "l",
    "g",
    "k",
    "h",
    "j",
    "q",
    "x",
    "r",
    "z",
    "c",
    "s",
    "y",
    "w",
)


def _language_family(language: str) -> str:
    tag = language.lower().replace("_", "-")
    if tag.startswith(("zh", "cmn")):
        return "zh"
    if tag.startswith("es"):
        return "es"
    if tag.startswith("en"):
        return "en"
    return "und"


def _is_han(token: str) -> bool:
    return bool(token and any("\u3400" <= character <= "\u9fff" for character in token))


# Apostrophes stay: they belong inside words such as "don't".
_EDGE_PUNCTUATION = ".,;:!?¡¿\"«»“”()[]…—"


def _latin_core(token: str) -> str:
    """A word token without the punctuation word-level aligners leave on it."""

    return unicodedata.normalize("NFC", token).strip(_EDGE_PUNCTUATION + " ")


def _is_latin_word_token(token: str) -> bool:
    normalized = _latin_core(token)
    if not normalized:
        return False
    return all(character.lower() in _SPANISH_LETTERS or character in {"'", "’"} for character in normalized)


_WORD_GAP_MS = 40.0


def _continues_latin_word(previous: AlignmentSpan, current: AlignmentSpan) -> bool:
    """True when ``current`` is the next character of the same written word.

    Character-level aligners (ElevenLabs) send one letter per span and a
    space span between words, so letters are glued back into a word. Word-level
    aligners (edge-tts, Azure, Whisper) already send whole words: each keeps its
    own timestamp, and is never glued to its neighbour. Gluing them spread a
    whole phrase evenly over its first and last word, ignoring the real word
    timings and pauses, so the mouth drifted away from the voice.
    """

    if not (_is_latin_word_token(previous.token) and _is_latin_word_token(current.token)):
        return False
    if _language_family(previous.language) != _language_family(current.language):
        return False
    if len(_latin_core(previous.token)) != 1 or len(_latin_core(current.token)) != 1:
        return False
    gap = current.start_ms - (previous.start_ms + previous.duration_ms)
    return gap <= _WORD_GAP_MS


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
        if _is_latin_word_token(spans[-1].token):
            # Withhold the trailing Latin word: one whole-word token, or the
            # run of character tokens that may still be growing.
            end -= 1
            while end and _continues_latin_word(spans[end - 1], spans[end]):
                end -= 1
        elif _is_han(spans[-1].token) and _language_family(spans[-1].language) in {"zh", "und"}:
            # Two following characters give phrase-aware pinyin enough context
            # for the common two- and three-character polyphonic cases.
            lookahead = 2
            while end and lookahead and _is_han(spans[end - 1].token):
                end -= 1
                lookahead -= 1
        return spans[:end]

    def planning_snapshot(self) -> list[AlignmentSpan]:
        """Return stable input plus Mandarin look-ahead used only for planning."""

        spans = self.snapshot()
        if (
            not self.done
            and spans
            and _is_han(spans[-1].token)
            and _language_family(spans[-1].language) in {"zh", "und"}
        ):
            return spans
        return self.stable_snapshot()


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


@lru_cache(maxsize=8192)
def spanish_phones(word: str, language: str = "es") -> tuple[str, ...]:
    """Return a compact Spanish phone sequence.

    The default ``es`` profile uses seseo (the common Latin-American mapping).
    ``es-ES`` preserves the Castilian /theta/ distinction for ``z`` and soft
    ``c``. The output is intentionally phonemic rather than allophonic because
    the current articulation IR cannot show most tongue-only contrasts.
    """

    value = unicodedata.normalize("NFC", word).lower().replace("’", "'")
    castilian = language.lower().replace("_", "-").startswith("es-es")
    accented = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}
    normalized = "".join(accented.get(character, character) for character in value)
    explicit_stress = {index for index, character in enumerate(value) if character in accented}
    vowels = {"a": "ES_A", "e": "ES_E", "i": "ES_I", "o": "ES_O", "u": "ES_U", "ü": "ES_U"}
    result: list[str] = []
    index = 0
    while index < len(normalized):
        character = normalized[index]
        following = normalized[index + 1] if index + 1 < len(normalized) else ""
        pair = normalized[index : index + 2]
        if pair == "ch":
            result.append("ES_CH")
            index += 2
            continue
        if pair == "ll":
            result.append("ES_Y")
            index += 2
            continue
        if pair == "rr":
            result.append("ES_RR")
            index += 2
            continue
        if character == "q" and following == "u":
            result.append("ES_K")
            index += 2
            continue
        if character == "g" and following in {"e", "i"}:
            result.append("ES_X")
            index += 1
            continue
        if character == "g" and following in {"u", "ü"} and index + 2 < len(normalized):
            after_u = normalized[index + 2]
            if after_u in {"e", "i"}:
                result.append("ES_G")
                if following == "ü":
                    result.append("ES_U")
                index += 2
                continue
        if character == "c":
            result.append(
                "ES_TH" if castilian and following in {"e", "i"} else ("ES_S" if following in {"e", "i"} else "ES_K")
            )
        elif character == "z":
            result.append("ES_TH" if castilian else "ES_S")
        elif character in {"b", "v"}:
            result.append("ES_B")
        elif character == "h":
            pass
        elif character == "j":
            result.append("ES_X")
        elif character == "ñ":
            result.append("ES_NY")
        elif character == "x":
            result.extend(("ES_K", "ES_S"))
        elif character == "y":
            result.append("ES_I" if index == len(normalized) - 1 else "ES_Y")
        elif character == "w":
            result.append("ES_W")
        elif character in vowels:
            symbol = vowels[character]
            result.append(f"{symbol}1" if index in explicit_stress else symbol)
        else:
            symbol = {
                "d": "ES_D",
                "f": "ES_F",
                "k": "ES_K",
                "l": "ES_L",
                "m": "ES_M",
                "n": "ES_N",
                "p": "ES_P",
                "r": "ES_RR" if index == 0 else "ES_R",
                "s": "ES_S",
                "t": "ES_T",
            }.get(character)
            if symbol:
                result.append(symbol)
        index += 1
    if not explicit_stress and normalized not in _SPANISH_CLITICS:
        # Default Spanish stress: the penultimate syllable when the word ends in a
        # vowel, n or s, otherwise the last one. Diphthongs (weak i/u next to a
        # vowel) count as one syllable, so stress the strong vowel.
        vowel_idx = [i for i, p in enumerate(result) if p in {"ES_A", "ES_E", "ES_I", "ES_O", "ES_U"}]
        nuclei = []
        for i in vowel_idx:
            if nuclei and nuclei[-1][-1] == i - 1 and (result[i] in {"ES_I", "ES_U"} or result[nuclei[-1][-1]] in {"ES_I", "ES_U"}):
                nuclei[-1].append(i)
            else:
                nuclei.append([i])
        if nuclei:
            last = normalized[-1:] if normalized else ""
            target = nuclei[-2] if len(nuclei) > 1 and last in set("aeiouns") else nuclei[-1]
            strong = [i for i in target if result[i] not in {"ES_I", "ES_U"}] or target
            result[strong[0]] = result[strong[0]] + "1"
    _spanish_glides(result)
    return tuple(result or ["ES_E"])


_ES_VOWELS = {"ES_A", "ES_E", "ES_I", "ES_O", "ES_U"}
# Unaccented function words lean on the next word and carry no stress of their
# own, so "la vida" opens big on "vi", not on "la".
_SPANISH_CLITICS = frozenset(
    "el la lo los las un una unos unas de del al a en con por para sin y e o u ni que "
    "me te se le les nos os mi mis tu tus su sus si pero como cuando donde mas".split()
)


def _spanish_glides(result: list[str]) -> None:
    """Unstressed i/u next to another vowel is a glide, not a syllable.

    "bueno", "quieres", "hoy", "aire": the weak vowel is a quick [j]/[w] on the
    way into or out of the strong one, so it gets a consonant-length slot
    instead of a full vowel's (written i/u with an accent, as in "día", stays a
    vowel). In "ui"/"iu" with no accent the first one glides ("muy", "ciudad").
    """

    def vowel(i: int) -> bool:
        return 0 <= i < len(result) and re.sub(r"1$", "", result[i]) in _ES_VOWELS

    for i, phone in enumerate(result):
        if phone not in {"ES_I", "ES_U"}:
            continue
        before = vowel(i - 1) and result[i - 1] not in {"ES_I", "ES_U"}  # still a vowel (not yet a glide)
        after = vowel(i + 1)
        if before or after:
            result[i] = "ES_J" if phone == "ES_I" else "ES_W"


def _split_tone(pinyin: str) -> tuple[str, int | None]:
    match = re.search(r"([1-5])$", pinyin)
    if not match:
        return pinyin, None
    return pinyin[:-1], int(match.group(1))


def _normalize_mandarin_final(initial: str, final: str) -> str:
    if initial == "y":
        return {
            "i": "i",
            "a": "ia",
            "e": "ie",
            "ao": "iao",
            "ou": "iou",
            "an": "ian",
            "in": "in",
            "ang": "iang",
            "ing": "ing",
            "ong": "iong",
            "u": "v",
            "ue": "ve",
            "uan": "van",
            "un": "vn",
        }.get(final, final)
    if initial == "w":
        return {
            "u": "u",
            "a": "ua",
            "o": "uo",
            "ai": "uai",
            "ei": "uei",
            "an": "uan",
            "en": "uen",
            "ang": "uang",
            "eng": "ueng",
        }.get(final, final)
    if initial in {"j", "q", "x"} and final.startswith("u"):
        final = f"v{final[1:]}"
    return {"iu": "iou", "ui": "uei", "un": "uen"}.get(final, final)


def _mandarin_final_phones(final: str, initial: str) -> list[str]:
    """Visible path of a Mandarin final: medial glide -> nucleus -> coda.

    Merges two designs. From the Lilyput Mandarin v1 spec: the 17 semantic
    targets, dynamic ``ai/ao/ei/ou`` primitives (one target that moves, rather
    than two flashes), j/q/x/y + u read as ü, and apical ``i`` kept out of the
    wide /i/ class. From the surface-phonetics pass: ``ian/üan/ie/üe`` use the
    mid-open front vowel ê, and nasal codas close the jaw again (-n tight,
    -ng half), so every character opens and closes.
    YI / WU / YU are short glides with the same lip targets as i / u / ü.
    """
    if final == "i" and initial in {"z", "c", "s"}:
        return ["ZH_IZ"]
    if final == "i" and initial in {"zh", "ch", "sh", "r"}:
        return ["ZH_IR"]
    if final == "er":
        return ["ZH_ER"]
    table = {
        "a": "A", "o": "O", "e": "E", "ê": "EH", "i": "I", "u": "U", "v": "V",
        "ai": "AI", "ei": "EI", "ao": "AO", "ou": "OU",
        "an": "A N", "en": "E N", "ang": "A NG", "eng": "E NG", "ong": "WU O NG",
        "ia": "YI A", "ie": "YI EH", "iao": "YI AO", "iou": "YI OU", "ian": "YI EH N",
        "in": "I N", "iang": "YI A NG", "ing": "I NG", "iong": "YU O NG",
        "ua": "WU A", "uo": "WU O", "uai": "WU AI", "uei": "WU EI", "uan": "WU A N",
        "uen": "WU E N", "uang": "WU A NG", "ueng": "WU E NG",
        "ve": "YU EH", "van": "YU EH N", "vn": "V N",
    }
    if final in table:
        return ["ZH_" + part for part in table[final].split()]
    nucleus = re.sub(r"(ng|n)$", "", final)
    values = {"a": "ZH_A", "o": "ZH_O", "e": "ZH_E", "i": "ZH_I", "u": "ZH_U", "v": "ZH_V"}
    phones = [values[character] for character in nucleus if character in values]
    return phones or ["ZH_E"]


@lru_cache(maxsize=4096)
def mandarin_syllable_phones(pinyin: str) -> tuple[tuple[str, ...], int | None]:
    value, tone = _split_tone(pinyin.lower().replace("ü", "v"))
    initial = next((candidate for candidate in _MANDARIN_INITIALS if value.startswith(candidate)), "")
    final = value[len(initial) :]
    final = _normalize_mandarin_final(initial, final)
    initial_symbol = {
        "b": "ZH_BPM",
        "p": "ZH_BPM",
        "m": "ZH_BPM",
        "f": "ZH_F",
        "d": "ZH_APICAL",
        "t": "ZH_APICAL",
        "n": "ZH_APICAL",
        "l": "ZH_APICAL",
        "g": "ZH_VELAR",
        "k": "ZH_VELAR",
        "h": "ZH_VELAR",
        "j": "ZH_PALATAL",
        "q": "ZH_PALATAL",
        "x": "ZH_PALATAL",
        "z": "ZH_DENTAL",
        "c": "ZH_DENTAL",
        "s": "ZH_DENTAL",
        "zh": "ZH_RETROFLEX",
        "ch": "ZH_RETROFLEX",
        "sh": "ZH_RETROFLEX",
        "r": "ZH_RETROFLEX",
    }.get(initial)
    result = ([initial_symbol] if initial_symbol else []) + _mandarin_final_phones(final, initial)
    return tuple(result or ["ZH_E"]), tone


def mandarin_readings(text: str) -> list[tuple[tuple[str, ...], int | None, float]]:
    """Return one phrase-aware reading per Han character.

    Without the optional dependency a deliberately low-confidence neutral
    fallback is returned; callers can still render a timeline, but documentation
    and the CLI make clear that real Mandarin support requires ``[mandarin]``.
    """

    try:
        from pypinyin import Style, lazy_pinyin  # type: ignore
    except ImportError:
        return [(("ZH_E",), None, 0.25) for _ in text]

    readings = lazy_pinyin(
        text,
        style=Style.TONE3,
        neutral_tone_with_five=True,
        errors=lambda value: list(value),
    )
    if len(readings) != len(text):
        return [(("ZH_E",), None, 0.25) for _ in text]
    result = []
    for reading in readings:
        symbols, tone = mandarin_syllable_phones(reading)
        result.append((symbols, tone, 1.0))
    return result


def _phone_weight(symbol: str, language: str) -> float:
    bare = re.sub(r"[012]$", "", symbol)
    family = _language_family(language)
    if family == "zh":
        # Inside the final: nucleus 2.1, glide 0.9, nasal coda 0.8. The initial
        # gets a fixed 28% of the syllable (see ``_allocate_mandarin``).
        if bare in {"ZH_N", "ZH_NG"}:
            return 0.8
        if bare in {"ZH_YI", "ZH_WU", "ZH_YU"}:
            return 0.9
        return 2.1 if bare in MANDARIN_FINALS else 0.45
    if family == "es":
        # Syllable-timed: every vowel keeps a full slot (no reduction), the
        # stressed one is about a quarter longer; glides and consonants are short.
        if bare in _ES_VOWELS:
            return 2.5 if symbol.endswith("1") else 2.0
        return 0.7 if bare in {"ES_J", "ES_W"} else 0.8
    vowel_bases = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
    return 2.1 if bare in vowel_bases else 0.8


MANDARIN_INITIALS = {"ZH_BPM", "ZH_F", "ZH_APICAL", "ZH_VELAR", "ZH_PALATAL", "ZH_DENTAL", "ZH_RETROFLEX"}
MANDARIN_FINALS = {
    "ZH_A", "ZH_O", "ZH_E", "ZH_EH", "ZH_I", "ZH_U", "ZH_V", "ZH_AI", "ZH_EI", "ZH_AO", "ZH_OU",
    "ZH_IZ", "ZH_IR", "ZH_ER",
}


def _allocate_mandarin(symbols, start_ms, duration_ms, language, *, confidence=1.0, tone=None):
    """Initial 28% / final 72% (Lilyput v1 prior); the final is split by weight."""
    if not symbols:
        return []
    # "er" alone is a final; zh/ch/sh/r followed by a final is an initial.
    has_initial = len(symbols) > 1 and symbols[0] in MANDARIN_INITIALS
    result = []
    cursor = start_ms
    finals = symbols
    if has_initial:
        length = duration_ms * 0.28
        result.append(TimedPhoneme(symbols[0], cursor, length, language, confidence, tone))
        cursor += length
        finals = symbols[1:]
        duration_ms *= 0.72
    weights = [_phone_weight(symbol, language) for symbol in finals]
    total = sum(weights)
    for symbol, weight in zip(finals, weights, strict=False):
        length = duration_ms * weight / total
        result.append(TimedPhoneme(symbol, cursor, length, language, confidence, tone))
        cursor += length
    return result


def _allocate(
    symbols: list[str],
    start_ms: float,
    duration_ms: float,
    language: str,
    *,
    confidence: float = 1.0,
    tone: int | None = None,
) -> list[TimedPhoneme]:
    if not symbols:
        return []
    weights = [_phone_weight(symbol, language) for symbol in symbols]
    total = sum(weights)
    cursor = start_ms
    result = []
    for symbol, weight in zip(symbols, weights, strict=False):
        length = duration_ms * weight / total
        result.append(TimedPhoneme(symbol, cursor, length, language, confidence, tone))
        cursor += length
    return result


_ZH_DIGITS = "零一二三四五六七八九"


def _mandarin_integer(number: int) -> str:
    """Spoken Mandarin for 0..9999 (12 -> 十二, 105 -> 一百零五)."""

    if number < 10:
        return _ZH_DIGITS[number]
    if number < 20:
        return "十" + (_ZH_DIGITS[number % 10] if number % 10 else "")
    units = ((1000, "千"), (100, "百"), (10, "十"))
    text, zero = "", False
    for value, name in units:
        digit = number // value % 10
        if digit:
            if zero and text:
                text += "零"
            text += _ZH_DIGITS[digit] + name
            zero = False
        elif text:
            zero = True
    if number % 10:
        text += ("零" if zero else "") + _ZH_DIGITS[number % 10]
    return text


def spell_mandarin_numbers(text: str) -> str:
    """Write Arabic numerals the way they are read aloud in Mandarin, so the
    mouth says them too: 10月8日 -> 十月八日, 12度 -> 十二度, 7:52 -> 七点五十二,
    3.5 -> 三点五, 2026年 -> 二零二六年. Longer digit strings are read digit by digit."""

    def clock(match: re.Match) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        spoken = _mandarin_integer(hour) + "点"
        if minute:
            spoken += ("零" if minute < 10 else "") + _mandarin_integer(minute)
        return spoken

    text = re.sub(r"(\d{1,2}):(\d{2})", clock, text)
    text = re.sub(r"(\d{4})(?=年)", lambda m: "".join(_ZH_DIGITS[int(d)] for d in m.group(1)), text)
    text = re.sub(r"(\d+)\.(\d+)", lambda m: spell_mandarin_numbers(m.group(1)) + "点" + "".join(_ZH_DIGITS[int(d)] for d in m.group(2)), text)
    return re.sub(
        r"\d+",
        lambda m: _mandarin_integer(int(m.group())) if len(m.group()) <= 4 else "".join(_ZH_DIGITS[int(d)] for d in m.group()),
        text,
    )


def alignment_to_phonemes(spans: Iterable[AlignmentSpan]) -> list[TimedPhoneme]:
    """Compile language-tagged English, Spanish, and Mandarin alignment."""

    spans = [
        AlignmentSpan(spell_mandarin_numbers(span.token), span.start_ms, span.duration_ms, span.language, span.confidence)
        if _language_family(span.language) == "zh" and re.search(r"\d", span.token)
        else span
        for span in spans
    ]
    result: list[TimedPhoneme] = []
    index = 0
    while index < len(spans):
        span = spans[index]
        if _is_latin_word_token(span.token):
            first = index
            chars: list[str] = []
            language = span.language
            family = _language_family(language)
            chars.append(_latin_core(span.token))
            index += 1
            while index < len(spans) and _continues_latin_word(spans[index - 1], spans[index]):
                chars.append(_latin_core(spans[index].token))
                index += 1
            start = spans[first].start_ms
            end = spans[index - 1].start_ms + spans[index - 1].duration_ms
            word = "".join(chars)
            if family == "es":
                symbols = list(spanish_phones(word, language))
            else:
                symbols = list(english_phones(word))
                language = "en" if family == "und" else language
            result.extend(_allocate(symbols, start, max(1.0, end - start), language, confidence=span.confidence))
            continue
        if _is_han(span.token):
            han_spans: list[AlignmentSpan] = []
            while index < len(spans) and _is_han(spans[index].token):
                item = spans[index]
                characters = [character for character in item.token if _is_han(character)]
                per_character = item.duration_ms / max(1, len(characters))
                for offset, character in enumerate(characters):
                    han_spans.append(
                        AlignmentSpan(
                            character,
                            item.start_ms + offset * per_character,
                            per_character,
                            item.language,
                            item.confidence,
                        )
                    )
                index += 1
            readings = mandarin_readings("".join(item.token for item in han_spans))
            for item, (symbols, tone, confidence) in zip(han_spans, readings, strict=False):
                language = item.language if _language_family(item.language) == "zh" else "zh-CN"
                result.extend(
                    _allocate_mandarin(
                        list(symbols),
                        item.start_ms,
                        max(1.0, item.duration_ms),
                        language,
                        confidence=min(item.confidence, confidence),
                        tone=tone,
                    )
                )
            continue
        index += 1
    _spanish_approximants(result)
    return result


def _spanish_approximants(phones: list[TimedPhoneme]) -> None:
    """Spanish b/v is a stop only after a pause or m/n; elsewhere ("la vida",
    "Cuba", "sabe") it is the approximant [β]: the lips come close but do not
    seal, so it must not show a full press. Runs across word boundaries."""

    for i, phone in enumerate(phones):
        if phone.symbol != "ES_B" or i == 0:
            continue
        previous = phones[i - 1]
        if _language_family(previous.language) != "es":
            continue
        gap = phone.start_ms - (previous.start_ms + previous.duration_ms)
        if gap <= _WORD_GAP_MS and previous.symbol not in {"ES_M", "ES_N"}:
            phones[i] = TimedPhoneme(
                "ES_BH", phone.start_ms, phone.duration_ms, phone.language, phone.confidence, phone.tone
            )
