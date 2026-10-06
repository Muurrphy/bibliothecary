"""Monroe lips: the dot-matrix mouth used on the Lilyput chest OLED.

This module carries the Lilyput "梦露嘴唇" design into the open package: the
pose parameters and landmark contours of ``make_lips.py``, the muscle-channel
targets of English v2, and the merged Mandarin targets. The exact 128x64
frames are generated once by ``tools/monroe/build_bank.py`` (Pillow) and
shipped as ``firmware/esp32_oled/monroe_frames.h`` and
``renderers/monroe_frames.js``; this module only decides which pose to show.

Geometry, in one paragraph: two sculpted upper lobes meet in a soft central
notch with a natural tubercle; from each Cupid's-bow peak the outer shoulder
pulls inward before returning to the corner (a concave S-curve, not a straight
diagonal); the lower lip is a wide cushion fuller than the upper lip whose rim
rises toward both corners. Opening lifts the upper lip a little and drops the
jaw a lot. A wider mouth must close and a taller mouth must narrow: the two
axes may never both reach their maximum.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

W, H = 128, 64
CX, CY = 64, 28
BASE_HALF_WIDTH = 49.0
OPENING_SCALE = 29.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


# ---------------------------------------------------------------------------
# Geometric pose (the original Monroe v1 parameters)


@dataclass(frozen=True)
class Pose:
    key: str
    openness: float
    width: float = 1.0
    pucker: float = 0.0
    smile: float = 0.0
    tilt: float = 0.0
    shift_x: float = 0.0
    upper_bias: float = 0.0
    lower_bias: float = 0.0


BASE_POSES = (
    Pose("REST", 0.00, 1.00),
    Pose("PRESS", 0.015, 0.93, pucker=0.18, smile=0.10, tilt=-0.22),
    Pose("SOFT", 0.13, 0.98, pucker=0.08, smile=0.04, tilt=0.15),
    Pose("PART", 0.32, 1.00, tilt=-0.10),
    Pose("WIDE_E", 0.48, 1.18, smile=0.78, upper_bias=-0.2),
    Pose("AH", 0.92, 1.00, smile=-0.08, lower_bias=0.6),
    Pose("OH", 1.18, 0.82, pucker=1.05, upper_bias=0.6, lower_bias=0.9),
    Pose("OO", 0.78, 0.68, pucker=1.30, smile=-0.12, upper_bias=0.8),
    Pose("BREATH", 0.78, 1.05, pucker=0.12, tilt=0.22, lower_bias=0.7),
    Pose("ASYM_L", 0.54, 1.12, smile=0.14, tilt=-1.08, shift_x=-4.0),
    Pose("ASYM_R", 0.58, 1.12, smile=-0.05, tilt=1.02, shift_x=4.0),
    Pose("DEEP_AH", 1.40, 0.96, pucker=0.08, lower_bias=1.0),
)


def blend_pose(key: str, a: Pose, b: Pose, amount: float = 0.5) -> Pose:
    """A true geometric in-between, not a cross-faded bitmap."""
    keep = 1.0 - amount
    return Pose(key, *(getattr(a, f.name) * keep + getattr(b, f.name) * amount for f in fields(Pose)[1:]))


POSES = BASE_POSES + (
    blend_pose("OPEN_RISE_1", BASE_POSES[3], BASE_POSES[5]),
    blend_pose("OPEN_RISE_2", BASE_POSES[5], BASE_POSES[11]),
    blend_pose("WIDE_RISE_1", BASE_POSES[2], BASE_POSES[3]),
    blend_pose("WIDE_RISE_2", BASE_POSES[3], BASE_POSES[4]),
    blend_pose("ROUND_RISE_1", BASE_POSES[1], BASE_POSES[7]),
    blend_pose("ROUND_RISE_2", BASE_POSES[7], BASE_POSES[6]),
    blend_pose("SIDE_L_RISE_1", BASE_POSES[2], BASE_POSES[9]),
    blend_pose("SIDE_L_RISE_2", BASE_POSES[9], BASE_POSES[8]),
    blend_pose("SIDE_R_RISE_1", BASE_POSES[2], BASE_POSES[10]),
    blend_pose("SIDE_R_RISE_2", BASE_POSES[10], BASE_POSES[8]),
    # Accents obey antagonistic coupling: no pose explodes along both axes.
    Pose("SCREAM_CROP", 1.76, 0.80, lower_bias=1.4),
    Pose("WIDE_CROP", 0.28, 1.18, smile=1.22, upper_bias=-0.1),
    Pose("ROUND_CROP", 1.48, 0.60, pucker=1.38, upper_bias=0.8, lower_bias=1.1),
    Pose("SIDE_L_CROP", 0.52, 1.15, smile=0.18, tilt=-1.55, shift_x=-7.0),
    Pose("SIDE_R_CROP", 0.54, 1.15, smile=-0.08, tilt=1.50, shift_x=7.0),
)


def requires_connected_corners(pose: Pose) -> bool:
    """Horizontal muscle families may never visually tear at the corners."""
    return "WIDE" in pose.key or "SIDE" in pose.key or pose.key.startswith("ASYM") or pose.key == "BREATH"


def lip_mass_heights(pose: Pose) -> tuple[float, float]:
    """Plush volume at rest/opening; thinner under lateral stretch."""
    stretch = _clamp((pose.width - 1.0) / 0.18)
    mass_scale = 1.0 - 0.22 * stretch
    upper_h = 24.5 * mass_scale + pose.upper_bias + 1.0 * pose.openness
    lower_h = 29.0 * mass_scale + pose.lower_bias + 1.2 * pose.openness
    return upper_h, lower_h


def upper_lip_dynamics(pose: Pose) -> tuple[float, float, float]:
    """Tubercle depth, inner arch and Cupid sculpt: opening and lateral pull
    flatten them, closure and rounding let the soft volumes return."""
    open_tension = _clamp(pose.openness / 1.40)
    lateral_tension = _clamp((pose.width - 1.0) / 0.18)
    pucker_release = _clamp(pose.pucker / 1.30)
    bead_strength = min(1.08, max(0.12, 1.0 - 0.72 * open_tension - 0.55 * lateral_tension + 0.35 * pucker_release))
    bead_v = 0.055 + 0.185 * bead_strength
    inner_arch_strength = min(1.05, max(0.28, 1.0 - 0.55 * open_tension - 0.42 * lateral_tension + 0.28 * pucker_release))
    inner_arch_v = -0.075 * inner_arch_strength
    outer_sculpt = min(1.06, max(0.58, 1.0 - 0.34 * open_tension - 0.25 * lateral_tension + 0.18 * pucker_release))
    return bead_v, inner_arch_v, outer_sculpt


_UPPER_OUTER_REST = (
    (-1.00, 0.00), (-0.93, -0.07), (-0.82, -0.14), (-0.70, -0.28), (-0.58, -0.48), (-0.47, -0.73),
    (-0.36, -1.00), (-0.25, -0.98), (-0.13, -0.78), (0.00, -0.56), (0.13, -0.78), (0.25, -0.98),
    (0.36, -1.00), (0.47, -0.73), (0.58, -0.48), (0.70, -0.28), (0.82, -0.14), (0.93, -0.07), (1.00, 0.00),
)
_UPPER_OUTER_TENSION = (
    (-1.00, 0.00), (-0.93, -0.06), (-0.82, -0.13), (-0.70, -0.27), (-0.58, -0.46), (-0.47, -0.65),
    (-0.36, -0.82), (-0.25, -0.78), (-0.13, -0.70), (0.00, -0.67), (0.13, -0.70), (0.25, -0.78),
    (0.36, -0.82), (0.47, -0.65), (0.58, -0.46), (0.70, -0.27), (0.82, -0.13), (0.93, -0.06), (1.00, 0.00),
)


def chaikin(points, rounds: int = 3):
    """Round a landmark polyline without the overshoot of a cubic spline."""
    curve = list(points)
    for _ in range(rounds):
        refined = [curve[0]]
        for a, b in zip(curve, curve[1:], strict=False):
            refined.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            refined.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        refined.append(curve[-1])
        curve = refined
    return curve


def lip_contours(pose: Pose, scale: float = 1.0):
    """Four outlines (upper outer, upper inner, lower inner, lower outer) in
    pixel coordinates of a (128*scale) x (64*scale) canvas."""
    half = BASE_HALF_WIDTH * pose.width
    upper_h, lower_h = lip_mass_heights(pose)
    opening = OPENING_SCALE * pose.openness
    upper_lift = 7.0 * pose.openness
    jaw_drop = 15.0 * pose.openness
    open_factor = _clamp((pose.openness - 0.55) / 0.65)
    narrow_factor = _clamp((1.08 - pose.width) / 0.28)
    corner_separation_px = 0.0 if requires_connected_corners(pose) else 4.0 * open_factor * narrow_factor
    lower_corner_v = corner_separation_px / lower_h
    bead_v, inner_arch_v, outer_sculpt = upper_lip_dynamics(pose)
    upper_outer_n = [(u, t + outer_sculpt * (r - t)) for (u, r), (_, t) in zip(_UPPER_OUTER_REST, _UPPER_OUTER_TENSION, strict=True)]
    a = inner_arch_v
    upper_inner_n = [
        (-1.00, 0.00), (-0.82, -0.035), (-0.62, -0.015), (-0.48, -0.010), (-0.38, a * 0.68), (-0.30, a),
        (-0.22, a * 0.62), (-0.14, bead_v * 0.23), (-0.07, bead_v * 0.72), (0.00, bead_v), (0.07, bead_v * 0.72),
        (0.14, bead_v * 0.23), (0.22, a * 0.62), (0.30, a), (0.38, a * 0.68), (0.48, -0.010), (0.62, -0.015),
        (0.82, -0.035), (1.00, 0.00),
    ]
    c = lower_corner_v
    lower_inner_n = [
        (-1.00, c), (-0.82, 0.06), (-0.62, 0.10), (-0.44, 0.17), (-0.27, 0.26), (-0.13, 0.32), (0.00, 0.35),
        (0.13, 0.32), (0.27, 0.26), (0.44, 0.17), (0.62, 0.10), (0.82, 0.06), (1.00, c),
    ]
    lower_outer_n = [
        (-1.00, c), (-0.92, 0.20), (-0.80, 0.42), (-0.64, 0.66), (-0.47, 0.85), (-0.28, 0.99), (0.00, 1.06),
        (0.28, 0.99), (0.47, 0.85), (0.64, 0.66), (0.80, 0.42), (0.92, 0.20), (1.00, c),
    ]

    def contour(normalized, height, inner=0, outer_motion=0):
        raw = []
        for u, v in normalized:
            x = CX + pose.shift_x + u * half
            y = CY + v * height
            aperture = max(0.0, 1.0 - u * u) ** (0.62 + 0.48 * pose.pucker)
            if inner < 0:
                y -= opening * 0.46 * aperture
            elif inner > 0:
                y += opening * 0.54 * aperture
            if outer_motion < 0:
                y -= upper_lift * aperture
            elif outer_motion > 0:
                y += jaw_drop * aperture
            y -= 4.2 * pose.smile * (abs(u) ** 1.8)
            y += 2.4 * pose.tilt * u
            raw.append((x * scale, y * scale))
        return chaikin(raw)

    return (
        contour(upper_outer_n, upper_h, outer_motion=-1),
        contour(upper_inner_n, upper_h, inner=-1),
        contour(lower_inner_n, lower_h, inner=1),
        contour(lower_outer_n, lower_h, outer_motion=1),
    )


# ---------------------------------------------------------------------------
# Muscle channels (the English v2 extension, now shared by every language)


@dataclass(frozen=True)
class MusclePose:
    key: str = "ANIM"
    jaw_open: float = 0.0
    lip_separation: float = 0.0
    mouth_width: float = 0.52
    lip_round: float = 0.04
    lip_protrusion: float = 0.02
    upper_lip_raise: float = 0.04
    lower_lip_depress: float = 0.04
    lip_press: float = 0.0
    lower_lip_tuck: float = 0.0
    corner_raise: float = 0.0
    asymmetry: float = 0.0


CHANNELS = tuple(f.name for f in fields(MusclePose) if f.name != "key")


def constrain(pose: MusclePose, key: str | None = None) -> MusclePose:
    """Muscle antagonism and closure invariants."""
    jaw, sep, width = _clamp(pose.jaw_open), _clamp(pose.lip_separation), _clamp(pose.mouth_width)
    press, rnd, prot = _clamp(pose.lip_press), _clamp(pose.lip_round), _clamp(pose.lip_protrusion)
    if jaw > 0.52:                       # a deep jaw pulls the corners in
        width = min(width, 0.72 - 0.42 * ((jaw - 0.52) / 0.48))
    if width > 0.72:                     # a strong lateral pull limits the jaw
        jaw = min(jaw, 0.48 - 0.24 * ((width - 0.72) / 0.28))
    sep *= 1.0 - 0.96 * press            # M/B/P owns the aperture
    jaw *= 1.0 - 0.80 * press
    width = min(width, 1.0 - 0.32 * rnd - 0.16 * prot)
    return MusclePose(
        key or pose.key, _clamp(jaw), _clamp(sep), _clamp(width), rnd, prot,
        _clamp(pose.upper_lip_raise), _clamp(pose.lower_lip_depress), press, _clamp(pose.lower_lip_tuck),
        _clamp(pose.corner_raise, -1.0, 1.0), _clamp(pose.asymmetry, -1.0, 1.0),
    )


def blend_muscles(weighted, key: str = "ANIM") -> MusclePose:
    total = sum(w for _, w in weighted)
    if total <= 0:
        return TARGETS["REST"]
    values = {c: sum(getattr(p, c) * w for p, w in weighted) / total for c in CHANNELS}
    return constrain(MusclePose(key, **values))


def legacy_pose(pose: MusclePose) -> Pose:
    pose = constrain(pose)
    openness = _clamp(0.98 * pose.jaw_open + 0.54 * pose.lip_separation, 0.0, 1.76)
    width = _clamp(0.74 + 0.48 * pose.mouth_width - 0.10 * pose.lip_round - 0.10 * pose.lip_protrusion - 0.08 * pose.jaw_open, 0.58, 1.18)
    pucker = _clamp(0.88 * pose.lip_round + 0.58 * pose.lip_protrusion, 0.0, 1.40)
    return Pose(
        key=pose.key, openness=openness, width=width, pucker=pucker, smile=0.88 * pose.corner_raise,
        tilt=2.6 * pose.asymmetry, shift_x=2.0 * pose.asymmetry,
        upper_bias=1.1 * pose.upper_lip_raise - 0.25 * pose.lip_press,
        lower_bias=1.2 * pose.lower_lip_depress - 0.45 * pose.lower_lip_tuck,
    )


def layer_offsets(pose: MusclePose) -> tuple[float, float]:
    """Independent vertical motion of the upper and lower lip, in 128x64 px."""
    up = -2.4 * pose.upper_lip_raise + 1.8 * pose.lip_press
    down = 2.4 * pose.lower_lip_depress + 1.6 * pose.jaw_open - 2.4 * pose.lip_press
    return up, down


# Hand-designed English targets (Monroe v2). Every language reuses them.
TARGETS = {
    p.key: constrain(p)
    for p in (
        MusclePose("REST", lip_separation=0.035, lip_press=0.12),
        MusclePose("PRESS_MBP", mouth_width=0.46, lip_round=0.14, lip_protrusion=0.10, lip_press=1.0),
        MusclePose("FV_TUCK", jaw_open=0.10, lip_separation=0.15, mouth_width=0.57, upper_lip_raise=0.18, lower_lip_tuck=1.0, asymmetry=-0.05),
        MusclePose("TH_DH", jaw_open=0.14, lip_separation=0.22, mouth_width=0.59, upper_lip_raise=0.12, lower_lip_depress=0.10),
        MusclePose("SOFT", jaw_open=0.15, lip_separation=0.22, mouth_width=0.53),
        MusclePose("WIDE_I", jaw_open=0.24, lip_separation=0.31, mouth_width=0.96, upper_lip_raise=0.13, corner_raise=0.20),
        MusclePose("MID_E", jaw_open=0.34, lip_separation=0.43, mouth_width=0.82, upper_lip_raise=0.17, corner_raise=0.10),
        MusclePose("OPEN_AE", jaw_open=0.64, lip_separation=0.72, mouth_width=0.60, upper_lip_raise=0.28, lower_lip_depress=0.52),
        MusclePose("OPEN_AH", jaw_open=0.76, lip_separation=0.82, mouth_width=0.52, upper_lip_raise=0.31, lower_lip_depress=0.68),
        MusclePose("DEEP_AA", jaw_open=1.0, lip_separation=0.96, mouth_width=0.34, upper_lip_raise=0.50, lower_lip_depress=1.0),
        MusclePose("ROUND_AO", jaw_open=0.66, lip_separation=0.72, mouth_width=0.36, lip_round=0.88, lip_protrusion=0.40, upper_lip_raise=0.25, lower_lip_depress=0.60),
        MusclePose("ROUND_OW", jaw_open=0.45, lip_separation=0.52, mouth_width=0.31, lip_round=0.90, lip_protrusion=0.62, lower_lip_depress=0.30),
        MusclePose("PUCKER_UW", jaw_open=0.25, lip_separation=0.36, mouth_width=0.18, lip_round=1.0, lip_protrusion=1.0),
        MusclePose("RHOTIC_ER", jaw_open=0.30, lip_separation=0.38, mouth_width=0.29, lip_round=0.58, lip_protrusion=0.68, asymmetry=0.05),
        MusclePose("BREATH_H", jaw_open=0.48, lip_separation=0.62, mouth_width=0.55, upper_lip_raise=0.28, lower_lip_depress=0.36, asymmetry=0.04),
        MusclePose("SIDE_L", jaw_open=0.26, lip_separation=0.31, mouth_width=0.68, upper_lip_raise=0.14, corner_raise=0.10, asymmetry=-0.34),
        MusclePose("SIDE_SH", jaw_open=0.29, lip_separation=0.35, mouth_width=0.48, lip_round=0.34, lip_protrusion=0.25, upper_lip_raise=0.19, asymmetry=0.20),
    )
}

# Mandarin targets (merged spec). Same muscle channels, so the OLED bank and
# the tablet renderer read them exactly like the English ones. zh/ch/sh/r, u, ü
# and o pout forward and slightly evert the upper lip (``upper_lip_raise``).
ZH_TARGETS = {
    p.key: constrain(p)
    for p in (
        MusclePose("ZH_BPM", mouth_width=0.46, lip_round=0.14, lip_protrusion=0.10, lip_press=1.0),
        MusclePose("ZH_F", jaw_open=0.10, lip_separation=0.15, mouth_width=0.57, upper_lip_raise=0.18, lower_lip_tuck=1.0, asymmetry=-0.04),
        MusclePose("ZH_APICAL", jaw_open=0.18, lip_separation=0.26, mouth_width=0.60, upper_lip_raise=0.06),
        MusclePose("ZH_VELAR", jaw_open=0.20, lip_separation=0.28, mouth_width=0.54, upper_lip_raise=0.06),
        MusclePose("ZH_PALATAL", jaw_open=0.20, lip_separation=0.27, mouth_width=0.72, upper_lip_raise=0.08, corner_raise=0.08),
        MusclePose("ZH_DENTAL", jaw_open=0.16, lip_separation=0.22, mouth_width=0.80, upper_lip_raise=0.10, corner_raise=0.12),
        MusclePose("ZH_RETROFLEX", jaw_open=0.24, lip_separation=0.32, mouth_width=0.42, lip_round=0.50, lip_protrusion=0.60, upper_lip_raise=0.22),
        MusclePose("ZH_ER", jaw_open=0.26, lip_separation=0.34, mouth_width=0.44, lip_round=0.46, lip_protrusion=0.50, upper_lip_raise=0.18),
        MusclePose("ZH_IZ", jaw_open=0.18, lip_separation=0.26, mouth_width=0.76, upper_lip_raise=0.10, corner_raise=0.10),
        MusclePose("ZH_IR", jaw_open=0.22, lip_separation=0.30, mouth_width=0.46, lip_round=0.42, lip_protrusion=0.48, upper_lip_raise=0.20),
        MusclePose("ZH_A", jaw_open=0.70, lip_separation=0.78, mouth_width=0.56, upper_lip_raise=0.30, lower_lip_depress=0.62),
        MusclePose("ZH_O", jaw_open=0.55, lip_separation=0.62, mouth_width=0.34, lip_round=0.88, lip_protrusion=0.50, upper_lip_raise=0.20, lower_lip_depress=0.45),
        MusclePose("ZH_E", jaw_open=0.34, lip_separation=0.42, mouth_width=0.70, upper_lip_raise=0.15, corner_raise=0.04),
        MusclePose("ZH_EH", jaw_open=0.44, lip_separation=0.54, mouth_width=0.74, upper_lip_raise=0.20, lower_lip_depress=0.20, corner_raise=0.08),
        MusclePose("ZH_I", jaw_open=0.22, lip_separation=0.30, mouth_width=0.86, upper_lip_raise=0.12, corner_raise=0.16),
        MusclePose("ZH_U", jaw_open=0.24, lip_separation=0.34, mouth_width=0.18, lip_round=1.0, lip_protrusion=1.0, upper_lip_raise=0.18),
        MusclePose("ZH_V", jaw_open=0.20, lip_separation=0.30, mouth_width=0.20, lip_round=1.0, lip_protrusion=0.75, upper_lip_raise=0.10),
        MusclePose("ZH_AI", jaw_open=0.54, lip_separation=0.62, mouth_width=0.64, upper_lip_raise=0.26, lower_lip_depress=0.40, corner_raise=0.06),
        MusclePose("ZH_AO", jaw_open=0.61, lip_separation=0.70, mouth_width=0.38, lip_round=0.76, lip_protrusion=0.40, upper_lip_raise=0.24, lower_lip_depress=0.52),
        MusclePose("ZH_EI", jaw_open=0.32, lip_separation=0.40, mouth_width=0.77, upper_lip_raise=0.15, corner_raise=0.10),
        MusclePose("ZH_OU", jaw_open=0.40, lip_separation=0.48, mouth_width=0.26, lip_round=0.94, lip_protrusion=0.70, upper_lip_raise=0.16, lower_lip_depress=0.25),
        MusclePose("ZH_N", jaw_open=0.10, lip_separation=0.10, mouth_width=0.58, upper_lip_raise=0.04),
        MusclePose("ZH_NG", jaw_open=0.20, lip_separation=0.26, mouth_width=0.52, upper_lip_raise=0.06),
    )
}

# English and Spanish refinements (same approach as Mandarin): reduced vowels
# stay small, lax vowels sit between their neighbours, sibilants close the teeth
# and spread, postalveolars pout, and /l/ is tongue-only (no sideways lip shift).
LANG_TARGETS = {
    p.key: constrain(p)
    for p in (
        MusclePose("EN_SCHWA", jaw_open=0.24, lip_separation=0.32, mouth_width=0.54, upper_lip_raise=0.08, lower_lip_depress=0.06),
        MusclePose("EN_LAX_I", jaw_open=0.26, lip_separation=0.34, mouth_width=0.80, upper_lip_raise=0.12, corner_raise=0.10),
        MusclePose("EN_LAX_U", jaw_open=0.30, lip_separation=0.38, mouth_width=0.36, lip_round=0.62, lip_protrusion=0.45, upper_lip_raise=0.12),
        MusclePose("EN_L", jaw_open=0.26, lip_separation=0.34, mouth_width=0.58, upper_lip_raise=0.08),
        MusclePose("EN_S", jaw_open=0.12, lip_separation=0.20, mouth_width=0.74, upper_lip_raise=0.10, corner_raise=0.10),
        MusclePose("EN_SH", jaw_open=0.22, lip_separation=0.30, mouth_width=0.38, lip_round=0.56, lip_protrusion=0.72, upper_lip_raise=0.24),
    )
}

# Dynamic primitives: one event whose target moves from start to end.
ZH_GLIDES = {"ZH_AI": ("ZH_A", "ZH_I"), "ZH_AO": ("ZH_A", "ZH_O"), "ZH_EI": ("ZH_EH", "ZH_I"), "ZH_OU": ("ZH_O", "ZH_U")}
EN_GLIDES = {"EN_AY": ("OPEN_AH", "WIDE_I"), "EN_AW": ("OPEN_AH", "ROUND_OW"), "EN_OY": ("ROUND_AO", "WIDE_I"),
             "EN_EY": ("MID_E", "WIDE_I"), "EN_OW": ("ROUND_AO", "ROUND_OW")}
GLIDES = {**ZH_GLIDES, **EN_GLIDES}

# Planner viseme -> muscle target name.
VISEME_TARGETS = {
    "REST": "REST", "PRESS": "PRESS_MBP", "FV": "FV_TUCK", "TH": "TH_DH", "SOFT": "SOFT",
    "WIDE_I": "WIDE_I", "MID_E": "MID_E", "OPEN_AE": "OPEN_AE", "OPEN_AH": "OPEN_AH", "DEEP_AA": "DEEP_AA",
    "ROUND_AO": "ROUND_AO", "ROUND_OW": "ROUND_OW", "PUCKER_UW": "PUCKER_UW", "RHOTIC_ER": "RHOTIC_ER",
    "BREATH_H": "BREATH_H", "SIDE_L": "SIDE_L", "SIDE_SH": "SIDE_SH",
    "ES_OPEN_A": "OPEN_AH", "ES_MID_E": "MID_E", "ES_WIDE_I": "WIDE_I", "ES_ROUND_O": "ROUND_OW",
    "ES_PUCKER_U": "PUCKER_UW", "ES_ALVEOLAR": "SOFT",
    **{name: name for name in ZH_TARGETS},
    **{name: name for name in LANG_TARGETS},
    **{name: start for name, (start, _) in EN_GLIDES.items()},
}


def target_for(viseme: str) -> MusclePose | None:
    name = VISEME_TARGETS.get(viseme)
    if name is None:
        return None
    return TARGETS.get(name) or ZH_TARGETS.get(name) or LANG_TARGETS.get(name)


def muscle_from_articulation(a) -> MusclePose:
    """Derive the three extra muscle channels from the eight-channel IR.

    The firmware does the same arithmetic, so a timeline streamed as plain
    articulation picks the same OLED frame on the board as in the preview."""
    def g(name, default=0.0):
        return float(getattr(a, name, default) if not isinstance(a, dict) else a.get(name, default))

    jaw, sep, width = g("jaw_open"), g("lip_separation"), g("mouth_width", 0.48)
    tuck, press = g("lower_lip_tuck"), g("lip_press")
    return constrain(MusclePose(
        "ANIM", jaw, sep, width, g("lip_round"), g("lip_protrusion"),
        upper_lip_raise=_clamp(0.40 * sep + 0.18 * tuck - 0.10 * press + 0.15 * g("lip_protrusion")),
        lower_lip_depress=_clamp((jaw - 0.35) * 1.55),
        lip_press=press, lower_lip_tuck=tuck,
        corner_raise=_clamp((width - 0.70) * 0.75, 0.0, 0.30),
        asymmetry=g("asymmetry"),
    ))


# Channel weights for picking the nearest OLED frame (open/width/round dominate).
_FRAME_WEIGHTS = {
    "jaw_open": 2.0, "lip_separation": 1.6, "mouth_width": 1.6, "lip_round": 1.4, "lip_protrusion": 0.8,
    "upper_lip_raise": 0.5, "lower_lip_depress": 0.7, "lip_press": 2.4, "lower_lip_tuck": 2.0,
    "corner_raise": 0.6, "asymmetry": 0.6,
}
V2_FIRST_FRAME = 27


def nearest_frame(pose: MusclePose) -> int:
    """Index (27..43) of the Monroe v2 frame closest to a muscle pose."""
    best, best_d = V2_FIRST_FRAME, float("inf")
    for i, target in enumerate(TARGETS.values()):
        d = sum(w * (getattr(pose, c) - getattr(target, c)) ** 2 for c, w in _FRAME_WEIGHTS.items())
        if d < best_d:
            best, best_d = V2_FIRST_FRAME + i, d
    return best


FRAME_INDEX = {}  # filled below


def _frame(name: str) -> int:
    return FRAME_INDEX["V2_" + name]


_LANDMARKS = {"PRESS_MBP", "FV_TUCK", "TH_DH", "DEEP_AA", "PUCKER_UW"}


def oled_frame(viseme: str, articulation=None, *, intensity: float = 1.0, duration_ms: float = 100.0) -> int:
    """The chest-OLED frame for one event (Lilyput readable rules).

    English and Spanish follow the "C" readable profile: unstressed vowels stop
    at mid-range, only long strong accents reach the extreme frames. Mandarin
    follows the Mandarin v1 table, extended with ê, apical vowels and codas.
    Unknown visemes fall back to the nearest frame by muscle channels."""
    i, d = intensity, duration_ms
    lang = {"EN_SCHWA": "SOFT", "EN_LAX_I": "MID_E", "EN_LAX_U": "ROUND_OW", "EN_L": "SOFT", "EN_S": "WIDE_I",
            "EN_SH": "SIDE_SH", "EN_OY": "ROUND_AO", "EN_OW": "ROUND_OW", "EN_EY": "MID_E"}
    if viseme in lang:
        return _frame(lang[viseme])
    if viseme in {"EN_AY", "EN_AW"}:
        return _frame("OPEN_AH" if i >= 0.78 else "OPEN_AE")
    zh = {
        "ZH_BPM": "PRESS_MBP", "ZH_F": "FV_TUCK", "ZH_DENTAL": "WIDE_I", "ZH_IZ": "WIDE_I",
        "ZH_RETROFLEX": "RHOTIC_ER", "ZH_IR": "RHOTIC_ER", "ZH_ER": "RHOTIC_ER", "ZH_E": "MID_E",
        "ZH_V": "PUCKER_UW", "ZH_U": "PUCKER_UW", "ZH_AI": "OPEN_AE", "ZH_AO": "ROUND_AO", "ZH_EI": "MID_E",
        "ZH_OU": "ROUND_OW", "ZH_N": "SOFT", "ZH_NG": "SOFT",
    }
    if viseme in zh:
        return _frame(zh[viseme])
    if viseme in {"ZH_APICAL", "ZH_VELAR", "ZH_PALATAL"}:
        # tongue-only initials show the lip preparation of their final
        r = getattr(articulation, "lip_round", 0.0) if articulation is not None else 0.0
        w = getattr(articulation, "mouth_width", 0.5) if articulation is not None else 0.5
        return _frame("ROUND_OW" if r >= 0.72 else "MID_E" if w >= 0.73 else "SOFT")
    if viseme == "ZH_A":
        return _frame("OPEN_AH" if i >= 0.82 and d >= 105 else "OPEN_AE")
    if viseme == "ZH_O":
        return _frame("ROUND_AO" if i >= 0.88 and d >= 120 else "ROUND_OW")
    if viseme == "ZH_I":
        return _frame("WIDE_I" if i >= 0.94 and d >= 135 else "MID_E")
    if viseme == "ZH_EH":
        return _frame("OPEN_AE" if i >= 0.90 and d >= 140 else "MID_E")
    # English / Spanish, readable "C" profile
    name = VISEME_TARGETS.get(viseme)
    if name == "WIDE_I":
        return _frame("WIDE_I" if i >= 0.95 and d >= 85 else "MID_E")
    if name == "OPEN_AE":
        return _frame("OPEN_AE" if i >= 0.78 else "SOFT")
    if name == "OPEN_AH":
        return _frame("OPEN_AH" if i >= 0.78 else "OPEN_AE")
    if name == "DEEP_AA":
        return _frame("DEEP_AA" if i >= 0.95 and d >= 125 else "OPEN_AH")
    if name == "ROUND_AO":
        return _frame("ROUND_AO" if i >= 0.90 and d >= 90 else "ROUND_OW")
    if name == "PUCKER_UW":
        return _frame("PUCKER_UW" if i >= 0.82 and d >= 80 else "ROUND_OW")
    if name == "BREATH_H" and d < 70:
        return _frame("SOFT")
    if name in TARGETS:
        return _frame(name)
    if articulation is not None:
        return nearest_frame(muscle_from_articulation(articulation))
    return _frame("SOFT")


def annotate_oled_frames(events) -> None:
    """Write ``metadata["oled_frame"]`` on every event, then remove unreadable
    flashes: on a 20 fps panel an ordinary change closer than 70 ms (55 ms in
    Mandarin) keeps the previous frame; closures, f/v, th, deep /a/ and the
    tight pucker are landmarks and always show."""
    landmark_frames = {_frame(n) for n in _LANDMARKS}
    previous = None
    for event in events:
        frame = oled_frame(event.viseme, event.articulation, intensity=event.intensity, duration_ms=event.duration_ms)
        if previous is not None:
            gap = event.start_ms - previous[0]
            limit = 55.0 if str(event.language).startswith(("zh", "cmn")) else 70.0
            if gap < limit and frame not in landmark_frames and previous[1] not in landmark_frames:
                frame = previous[1]
        try:
            event.metadata["oled_frame"] = frame
        except TypeError:  # read-only mapping
            object.__setattr__(event, "metadata", {**event.metadata, "oled_frame": frame})
        if previous is None or frame != previous[1]:
            previous = (event.start_ms, frame)


# The 44 frames flashed into the chest board: Monroe v1 (0..26) + v2 (27..43).
FRAME_NAMES = tuple("V1_" + p.key for p in POSES) + tuple("V2_" + k for k in TARGETS)
FRAME_INDEX.update({name: index for index, name in enumerate(FRAME_NAMES)})


def muscle_dict(pose: MusclePose) -> dict:
    data = asdict(pose)
    data.pop("key")
    return data


__all__ = [
    "BASE_POSES", "CHANNELS", "FRAME_NAMES", "MusclePose", "POSES", "Pose", "TARGETS", "VISEME_TARGETS",
    "EN_GLIDES", "GLIDES", "LANG_TARGETS", "ZH_GLIDES", "ZH_TARGETS", "blend_muscles", "constrain", "layer_offsets", "legacy_pose", "lip_contours",
    "annotate_oled_frames", "muscle_from_articulation", "nearest_frame", "oled_frame", "target_for",
]
