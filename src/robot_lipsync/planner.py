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
}


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
        shape = SHAPES[name]
        next_shape = SHAPES[expanded[index + 1][1]] if index + 1 < len(expanded) else SHAPES["REST"]
        if name not in {"PRESS", "FV", "TH"}:
            shape = _blend(shape, next_shape, 0.14)
        else:
            shape = enforce_constraints(shape)
        match = re.search(r"([012])$", phoneme.symbol)
        stress = int(match.group(1)) if match else -1
        intensity = 1.0 if stress == 1 else (0.82 if stress == 2 else 0.70)
        events.append(
            ArticulationEvent(
                session_id=session_id,
                start_ms=max(0.0, audio_start - visual_lead_ms),
                duration_ms=max(minimum_readable_ms, duration + visual_lead_ms),
                viseme=name,
                articulation=shape,
                intensity=intensity,
                language=phoneme.language,
                confidence=phoneme.confidence,
                metadata={"phoneme": phoneme.symbol},
            )
        )
    return events
