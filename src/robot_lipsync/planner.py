"""Muscle-aware phoneme-to-articulation planning with causal coarticulation."""

from __future__ import annotations

import re

from .events import Articulation, ArticulationEvent
from .phonemes import TimedPhoneme

SHAPES: dict[str, Articulation] = {
    "REST": Articulation(0.00, 0.01, 0.48, 0.05, 0.18),
    "PRESS": Articulation(0.01, 0.00, 0.43, 0.18, 1.00),
    "FV": Articulation(0.09, 0.06, 0.54, 0.06, 0.42, lower_lip_tuck=0.82),
    "TH": Articulation(0.18, 0.12, 0.54, 0.04, 0.08),
    "SOFT": Articulation(0.18, 0.12, 0.52, 0.06, 0.08),
    "WIDE_I": Articulation(0.24, 0.18, 0.96, 0.02, 0.02),
    "MID_E": Articulation(0.34, 0.30, 0.82, 0.03, 0.02),
    "OPEN_AE": Articulation(0.64, 0.64, 0.60, 0.03, 0.00),
    "OPEN_AH": Articulation(0.76, 0.78, 0.52, 0.04, 0.00),
    "DEEP_AA": Articulation(1.00, 1.00, 0.34, 0.04, 0.00),
    "ROUND_AO": Articulation(0.66, 0.64, 0.36, 0.88, 0.00, lip_protrusion=0.62),
    "ROUND_OW": Articulation(0.45, 0.42, 0.31, 0.92, 0.01, lip_protrusion=0.76),
    "PUCKER_UW": Articulation(0.25, 0.18, 0.18, 1.00, 0.02, lip_protrusion=1.00),
    "RHOTIC_ER": Articulation(0.30, 0.22, 0.29, 0.62, 0.02, lip_protrusion=0.44, asymmetry=0.05),
    "BREATH_H": Articulation(0.48, 0.52, 0.55, 0.10, 0.00, asymmetry=0.04),
    "SIDE_L": Articulation(0.26, 0.18, 0.68, 0.04, 0.04, asymmetry=-0.34),
    "SIDE_SH": Articulation(0.29, 0.22, 0.48, 0.34, 0.03, asymmetry=0.20),
    # Spanish's stable five-vowel system benefits from dedicated targets rather
    # than forcing its vowels through English CMU categories.
    "ES_OPEN_A": Articulation(0.84, 0.86, 0.46, 0.02, 0.00),
    "ES_MID_E": Articulation(0.40, 0.34, 0.78, 0.02, 0.00),
    "ES_WIDE_I": Articulation(0.20, 0.14, 0.94, 0.01, 0.00),
    "ES_ROUND_O": Articulation(0.48, 0.44, 0.34, 0.84, 0.00, lip_protrusion=0.60),
    "ES_PUCKER_U": Articulation(0.20, 0.13, 0.18, 0.98, 0.00, lip_protrusion=0.96),
    "ES_ALVEOLAR": Articulation(0.20, 0.14, 0.66, 0.02, 0.03),
    # Mandarin: the 17 semantic targets of the Lilyput Mandarin v1 spec plus ê,
    # the apical vowels and the two nasal codas. Values are the eight-channel
    # projection of the muscle targets in ``monroe.ZH_TARGETS``.
    "ZH_BPM": Articulation(0.00, 0.01, 0.46, 0.14, 1.00, lip_protrusion=0.10),
    "ZH_F": Articulation(0.10, 0.15, 0.57, 0.05, 0.00, lower_lip_tuck=1.00, asymmetry=-0.04),
    "ZH_APICAL": Articulation(0.18, 0.26, 0.60, 0.04, 0.00),
    "ZH_VELAR": Articulation(0.20, 0.28, 0.54, 0.06, 0.00),
    "ZH_PALATAL": Articulation(0.20, 0.27, 0.72, 0.03, 0.00),
    "ZH_DENTAL": Articulation(0.16, 0.22, 0.80, 0.02, 0.00),
    "ZH_RETROFLEX": Articulation(0.24, 0.32, 0.42, 0.50, 0.00, lip_protrusion=0.60),
    "ZH_ER": Articulation(0.26, 0.34, 0.44, 0.46, 0.00, lip_protrusion=0.50),
    "ZH_IZ": Articulation(0.18, 0.26, 0.76, 0.02, 0.00),
    "ZH_IR": Articulation(0.22, 0.30, 0.46, 0.42, 0.00, lip_protrusion=0.48),
    "ZH_A": Articulation(0.70, 0.78, 0.56, 0.03, 0.00),
    "ZH_O": Articulation(0.55, 0.62, 0.34, 0.88, 0.00, lip_protrusion=0.50),
    "ZH_E": Articulation(0.34, 0.42, 0.70, 0.03, 0.00),
    "ZH_EH": Articulation(0.44, 0.54, 0.74, 0.02, 0.00),
    "ZH_I": Articulation(0.22, 0.30, 0.86, 0.02, 0.00),
    "ZH_U": Articulation(0.24, 0.34, 0.18, 1.00, 0.00, lip_protrusion=1.00),
    "ZH_V": Articulation(0.20, 0.30, 0.20, 1.00, 0.00, lip_protrusion=0.75),
    "ZH_AI": Articulation(0.54, 0.62, 0.64, 0.03, 0.00),
    "ZH_AO": Articulation(0.61, 0.70, 0.38, 0.76, 0.00, lip_protrusion=0.40),
    "ZH_EI": Articulation(0.32, 0.40, 0.77, 0.02, 0.00),
    "ZH_OU": Articulation(0.40, 0.48, 0.26, 0.94, 0.00, lip_protrusion=0.70),
    "ZH_N": Articulation(0.10, 0.10, 0.58, 0.03, 0.00),
    "ZH_NG": Articulation(0.20, 0.26, 0.52, 0.06, 0.00),
}


MANDARIN_LANDMARKS = {"ZH_BPM", "ZH_F"}
_MANDARIN_INITIAL_TARGETS = {"ZH_BPM", "ZH_F", "ZH_APICAL", "ZH_VELAR", "ZH_PALATAL", "ZH_DENTAL", "ZH_RETROFLEX"}


def _mandarin_role(name: str) -> str:
    return "initial" if name in _MANDARIN_INITIAL_TARGETS else "final"


def _bare(phone: str) -> str:
    return re.sub(r"[012]$", "", phone.upper())


def enforce_constraints(shape: Articulation) -> Articulation:
    """Prevent anatomically implausible simultaneous width and jaw extremes."""

    jaw = shape.jaw_open
    width = shape.mouth_width
    if jaw > 0.58:
        width = min(width, 0.66 - 0.34 * ((jaw - 0.58) / 0.42))
    if width > 0.68:
        jaw = min(jaw, 0.50 - 0.24 * ((width - 0.68) / 0.32))
    return Articulation(
        jaw_open=max(0.0, min(1.0, jaw)),
        lip_separation=min(shape.lip_separation, max(0.05, jaw + 0.10)),
        mouth_width=max(0.0, min(1.0, width)),
        lip_round=shape.lip_round,
        lip_press=shape.lip_press,
        lip_protrusion=shape.lip_protrusion,
        lower_lip_tuck=shape.lower_lip_tuck,
        asymmetry=shape.asymmetry,
    )


def _blend(a: Articulation, b: Articulation, amount: float) -> Articulation:
    fields = (
        "jaw_open",
        "lip_separation",
        "mouth_width",
        "lip_round",
        "lip_press",
        "lip_protrusion",
        "lower_lip_tuck",
        "asymmetry",
    )
    values = {name: getattr(a, name) * (1.0 - amount) + getattr(b, name) * amount for name in fields}
    return enforce_constraints(Articulation(**values))


def _targets(phone: str) -> list[str]:
    symbol = _bare(phone)
    multilingual = {
        "ES_A": "ES_OPEN_A",
        "ES_E": "ES_MID_E",
        "ES_I": "ES_WIDE_I",
        "ES_O": "ES_ROUND_O",
        "ES_U": "ES_PUCKER_U",
        "ES_W": "ES_PUCKER_U",
        "ES_B": "PRESS",
        "ES_P": "PRESS",
        "ES_M": "PRESS",
        "ES_F": "FV",
        "ES_TH": "TH",
        "ES_CH": "SIDE_SH",
        "ES_Y": "ES_WIDE_I",
        "ES_D": "ES_ALVEOLAR",
        "ES_T": "ES_ALVEOLAR",
        "ES_N": "ES_ALVEOLAR",
        "ES_NY": "ES_ALVEOLAR",
        "ES_L": "ES_ALVEOLAR",
        "ES_R": "ES_ALVEOLAR",
        "ES_RR": "ES_ALVEOLAR",
        "ES_S": "ES_ALVEOLAR",
        "ES_K": "SOFT",
        "ES_G": "SOFT",
        "ES_X": "SOFT",
        # Mandarin glides share the lip target of their vowel.
        "ZH_YI": "ZH_I",
        "ZH_WU": "ZH_U",
        "ZH_YU": "ZH_V",
    }
    if symbol in multilingual:
        return [multilingual[symbol]]
    if symbol.startswith("ZH_") and symbol in SHAPES:
        return [symbol]
    diphthongs = {
        "AY": ["OPEN_AH", "WIDE_I"],
        "AW": ["OPEN_AH", "ROUND_OW"],
        "OY": ["ROUND_AO", "WIDE_I"],
        "EY": ["MID_E", "WIDE_I"],
        "OW": ["ROUND_AO", "ROUND_OW"],
    }
    if symbol in diphthongs:
        return diphthongs[symbol]
    return [
        {
            "M": "PRESS",
            "B": "PRESS",
            "P": "PRESS",
            "F": "FV",
            "V": "FV",
            "TH": "TH",
            "DH": "TH",
            "W": "PUCKER_UW",
            "UW": "PUCKER_UW",
            "UH": "PUCKER_UW",
            "R": "RHOTIC_ER",
            "ER": "RHOTIC_ER",
            "Y": "WIDE_I",
            "IY": "WIDE_I",
            "IH": "WIDE_I",
            "EH": "MID_E",
            "AE": "OPEN_AE",
            "AH": "OPEN_AH",
            "AA": "DEEP_AA",
            "AO": "ROUND_AO",
            "L": "SIDE_L",
            "S": "SIDE_L",
            "Z": "SIDE_L",
            "SH": "SIDE_SH",
            "ZH": "SIDE_SH",
            "CH": "SIDE_SH",
            "JH": "SIDE_SH",
            "H": "BREATH_H",
            "SYLLABLE": "SOFT",
        }.get(symbol, "SOFT")
    ]


def phonemes_to_articulation(
    session_id: str,
    phonemes: list[TimedPhoneme],
    *,
    visual_lead_ms: float = 42.0,
    minimum_readable_ms: float = 70.0,
) -> list[ArticulationEvent]:
    """Compile phonemes into causal, readable articulation events."""

    expanded: list[tuple[TimedPhoneme, str, float, float]] = []
    for phoneme in phonemes:
        names = _targets(phoneme.symbol)
        if len(names) > 1 and phoneme.duration_ms < 180:
            names = names[-1:]
        duration = phoneme.duration_ms / len(names)
        for index, name in enumerate(names):
            expanded.append((phoneme, name, phoneme.start_ms + index * duration, duration))

    events: list[ArticulationEvent] = []
    for index, (phoneme, name, audio_start, duration) in enumerate(expanded):
        family = phoneme.language.lower().replace("_", "-").split("-", 1)[0]
        mandarin = family in {"zh", "cmn"}
        shape = SHAPES[name]
        next_shape = SHAPES[expanded[index + 1][1]] if index + 1 < len(expanded) else SHAPES["REST"]
        role = _mandarin_role(name) if mandarin else ""
        if mandarin and role == "initial" and name not in MANDARIN_LANDMARKS:
            # Mandarin CV co-onset: a non-closing initial already takes on part
            # of the following final's rounding or spreading. Rounded finals
            # anticipate most, spread ones less, open /a/ least (20-42%).
            nxt = next_shape
            amount = 0.42 if nxt.lip_round >= 0.80 else (0.30 if nxt.mouth_width >= 0.78 else 0.20)
            shape = _blend(shape, nxt, amount)
        elif name not in {"PRESS", "FV", "TH"} | MANDARIN_LANDMARKS:
            shape = _blend(shape, next_shape, 0.20 if mandarin else 0.14)
        else:
            shape = enforce_constraints(shape)
        match = re.search(r"([012])$", phoneme.symbol)
        if mandarin:
            intensity = min(1.0, 0.72 + duration / 500.0)
            if phoneme.tone == 5:
                intensity = min(intensity, 0.80)
        else:
            stress = int(match.group(1)) if match else -1
            intensity = 1.0 if stress == 1 else (0.82 if stress == 2 else 0.70)
        metadata = {"phoneme": phoneme.symbol, "audio_start_ms": round(float(audio_start), 3)}
        if phoneme.tone is not None:
            metadata["tone"] = phoneme.tone
        if role:
            metadata["syllable_role"] = role
        # A Mandarin final takes over at its acoustic onset; only the initial
        # keeps the visual lead, so b/p/m and f stay readable for a frame.
        lead = 0.0 if role == "final" else visual_lead_ms
        events.append(
            ArticulationEvent(
                session_id=session_id,
                start_ms=max(0.0, audio_start - lead),
                duration_ms=max(minimum_readable_ms, duration + lead),
                viseme=name,
                articulation=shape,
                intensity=intensity,
                language=phoneme.language,
                confidence=phoneme.confidence,
                metadata=metadata,
            )
        )
    from .monroe import annotate_oled_frames  # local import keeps planner light

    annotate_oled_frames(events)
    return events
