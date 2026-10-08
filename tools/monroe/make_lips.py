#!/usr/bin/env python3
"""Generate Lilyput chest-screen lip poses for a 128x64 monochrome OLED.

The named release "梦露嘴唇" uses a natural, muscle-responsive tubercle with
conditional anti-spike cleanup when the lowest row quantizes to one cell:
the old lens/almond formula:
- young, plush lips made from three volumes: two soft upper lobes and one broad
  lower cushion;
- a regular 2x2-on / 1px-off digital-cell grid, with no wrinkle-like dithering;
- a curved central lip bead that is never narrower than three luminous cells;
- real vertical articulation: the upper lip lifts and the lower lip/jaw descends;
- strong vowels deliberately exceed the OLED crop, while rest remains complete;
- the central black aperture is about 1.5x taller and strong A/O shapes are narrower;
- the vertical and horizontal axes may not both reach their maximum: a mouth
  that opens farther must narrow, while a mouth that stretches wider must close;
- open accents crop vertically, wide accents stay modest and close vertically,
  and round accents contract laterally instead of expanding in every direction;
- two rounded upper-lip lobes form a clean Cupid's bow and central tubercle;
- each outer upper-lip shoulder tapers inward before returning to the corner,
  replacing the old straight/convex diagonal with a subtle concave S-curve;
- the inner upper-lip edge rolls broadly beneath each lobe and flows into the
  central tubercle without narrow V-shaped cuts;
- vertical opening and lateral stretch flatten the tubercle and Cupid's bow,
  while closed and puckered poses restore their fuller sculpted curvature;
- the lowest tubercle pixels now come only from the natural contour sampling,
  avoiding the square "meatball" created by a forced three-cell underline;
- if that natural contour ends in one lone cell with a wider connected row
  immediately above it, only the terminal spike is trimmed away;
- the fuller lower cushion rises decisively toward both corners instead of
  collapsing into a generic half-ellipse;
- horizontal and side-pull families must keep both mouth corners connected;
  visible corner separation is reserved for narrow, vertically open poses;
- twelve main visemes, ten geometric in-betweens and five accent crops.

Outputs are written next to this script:
  lip_frames.h
  梦露嘴唇_静态预览.png
  梦露嘴唇_动态预览.gif
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


W, H = 128, 64
# Rest is slightly high so an open jaw has room to descend toward row 63.
CX, CY = 64, 28
BASE_HALF_WIDTH = 49.0
OPENING_SCALE = 29.0
OUTPUT_DIR = Path(__file__).resolve().parent


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
    # Human lateral stretch is modest. Even a strong E stays within 1.18x,
    # while progressively deeper open vowels pull their corners inward.
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
    """Create a true geometric in-between, not a cross-faded bitmap."""
    keep = 1.0 - amount
    return Pose(
        key,
        a.openness * keep + b.openness * amount,
        a.width * keep + b.width * amount,
        a.pucker * keep + b.pucker * amount,
        a.smile * keep + b.smile * amount,
        a.tilt * keep + b.tilt * amount,
        a.shift_x * keep + b.shift_x * amount,
        a.upper_bias * keep + b.upper_bias * amount,
        a.lower_bias * keep + b.lower_bias * amount,
    )


def requires_connected_corners(pose: Pose) -> bool:
    """Horizontal muscle families may never visually tear at the corners."""
    return (
        "WIDE" in pose.key
        or "SIDE" in pose.key
        or pose.key.startswith("ASYM")
        or pose.key == "BREATH"
    )


def lip_mass_heights(pose: Pose) -> tuple[float, float]:
    """Preserve plush volume at rest/opening; thin it under lateral stretch."""
    stretch = min(1.0, max(0.0, (pose.width - 1.0) / 0.18))
    mass_scale = 1.0 - 0.22 * stretch
    upper_h = 24.5 * mass_scale + pose.upper_bias + 1.0 * pose.openness
    lower_h = 29.0 * mass_scale + pose.lower_bias + 1.2 * pose.openness
    return upper_h, lower_h


def upper_lip_dynamics(pose: Pose) -> tuple[float, float, float]:
    """Return tubercle depth, broad inner arch, and outer Cupid sculpt strength.

    A lip landmark is not glued to the face: opening and transverse pull stretch
    it flatter, while closure and rounding let the soft upper-lip volumes return.
    The values remain normalized so the same rule works across all pose widths.
    """
    open_tension = min(1.0, max(0.0, pose.openness / 1.40))
    lateral_tension = min(1.0, max(0.0, (pose.width - 1.0) / 0.18))
    pucker_release = min(1.0, max(0.0, pose.pucker / 1.30))

    bead_strength = min(
        1.08,
        max(
            0.12,
            1.0
            - 0.72 * open_tension
            - 0.55 * lateral_tension
            + 0.35 * pucker_release,
        ),
    )
    bead_v = 0.055 + 0.185 * bead_strength

    inner_arch_strength = min(
        1.05,
        max(
            0.28,
            1.0
            - 0.55 * open_tension
            - 0.42 * lateral_tension
            + 0.28 * pucker_release,
        ),
    )
    inner_arch_v = -0.075 * inner_arch_strength

    outer_sculpt = min(
        1.06,
        max(
            0.58,
            1.0
            - 0.34 * open_tension
            - 0.25 * lateral_tension
            + 0.18 * pucker_release,
        ),
    )
    return bead_v, inner_arch_v, outer_sculpt


# The first twelve public poses stay at their original indexes. Ten additional
# muscle in-betweens turn each articulatory family into a five-step path.
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
    # Sixth-stage accents obey antagonistic muscle coupling. An open jaw pulls
    # the corners inward; a transverse pull closes the jaw; a strong rounded
    # vowel becomes taller and narrower. No pose may explode along both axes.
    Pose("SCREAM_CROP", 1.76, 0.80, lower_bias=1.4),
    Pose("WIDE_CROP", 0.28, 1.18, smile=1.22, upper_bias=-0.1),
    Pose("ROUND_CROP", 1.48, 0.60, pucker=1.38, upper_bias=0.8, lower_bias=1.1),
    Pose("SIDE_L_CROP", 0.52, 1.15, smile=0.18, tilt=-1.55, shift_x=-7.0),
    Pose("SIDE_R_CROP", 0.54, 1.15, smile=-0.08, tilt=1.50, shift_x=7.0),
)


def chaikin(points: list[tuple[float, float]], rounds: int = 3) -> list[tuple[float, float]]:
    """Round a landmark polyline without the overshoot of a cubic spline."""
    curve = points
    for _ in range(rounds):
        refined = [curve[0]]
        for a, b in zip(curve, curve[1:]):
            refined.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            refined.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        refined.append(curve[-1])
        curve = refined
    return curve


def build_solid_lips(pose: Pose) -> tuple[np.ndarray, np.ndarray]:
    """Build separate upper-lobe and lower-cushion volumes from landmarks."""
    half = BASE_HALF_WIDTH * pose.width
    # The shared silhouette carries the beauty; pose parameters only articulate
    # it. The lower cushion is deliberately fuller than the upper lobes.
    upper_h, lower_h = lip_mass_heights(pose)
    opening = OPENING_SCALE * pose.openness
    upper_lift = 7.0 * pose.openness
    jaw_drop = 15.0 * pose.openness

    # Narrow, vertically open mouths may visually separate at the corners.
    # Horizontal and side-pull families receive zero separation and are also
    # reconnected after pixel-grid sampling.
    open_factor = min(1.0, max(0.0, (pose.openness - 0.55) / 0.65))
    narrow_factor = min(1.0, max(0.0, (1.08 - pose.width) / 0.28))
    corner_separation_px = 0.0 if requires_connected_corners(pose) else (
        4.0 * open_factor * narrow_factor
    )
    lower_corner_v = corner_separation_px / lower_h
    bead_v, inner_arch_v, outer_sculpt = upper_lip_dynamics(pose)

    # These are sculpted lip masses rather than ellipses. Two broad upper lobes
    # roll into a soft central notch. From each peak, the outer shoulder first
    # pulls inward and thins before returning to the mouth corner, producing a
    # graphic concave curve instead of a straight diagonal. The lower lip is a
    # wide cushion whose outline and inner rim both rise toward the corners.
    upper_outer_rest_n = [
        (-1.00, 0.00), (-0.93, -0.07), (-0.82, -0.14),
        (-0.70, -0.28), (-0.58, -0.48), (-0.47, -0.73),
        (-0.36, -1.00),
        (-0.25, -0.98), (-0.13, -0.78), (0.00, -0.56),
        (0.13, -0.78), (0.25, -0.98), (0.36, -1.00),
        (0.47, -0.73), (0.58, -0.48), (0.70, -0.28),
        (0.82, -0.14), (0.93, -0.07), (1.00, 0.00),
    ]
    # Under tension the Cupid landmarks do not disappear, but their height
    # difference becomes smaller. Blend the relaxed sculpture toward this
    # gentler target instead of scaling the entire upper lip as one rigid mask.
    upper_outer_tension_n = [
        (-1.00, 0.00), (-0.93, -0.06), (-0.82, -0.13),
        (-0.70, -0.27), (-0.58, -0.46), (-0.47, -0.65),
        (-0.36, -0.82),
        (-0.25, -0.78), (-0.13, -0.70), (0.00, -0.67),
        (0.13, -0.70), (0.25, -0.78), (0.36, -0.82),
        (0.47, -0.65), (0.58, -0.46), (0.70, -0.27),
        (0.82, -0.13), (0.93, -0.06), (1.00, 0.00),
    ]
    upper_outer_n = [
        (u, target_v + outer_sculpt * (rest_v - target_v))
        for (u, rest_v), (_, target_v)
        in zip(upper_outer_rest_n, upper_outer_tension_n)
    ]
    upper_inner_n = [
        (-1.00, 0.00), (-0.82, -0.035), (-0.62, -0.015),
        (-0.48, -0.010),
        (-0.38, inner_arch_v * 0.68),
        (-0.30, inner_arch_v),
        (-0.22, inner_arch_v * 0.62),
        (-0.14, bead_v * 0.23),
        (-0.07, bead_v * 0.72),
        (0.00, bead_v),
        (0.07, bead_v * 0.72),
        (0.14, bead_v * 0.23),
        (0.22, inner_arch_v * 0.62),
        (0.30, inner_arch_v),
        (0.38, inner_arch_v * 0.68),
        (0.48, -0.010),
        (0.62, -0.015), (0.82, -0.035), (1.00, 0.00),
    ]
    lower_inner_n = [
        (-1.00, lower_corner_v), (-0.82, 0.06), (-0.62, 0.10),
        (-0.44, 0.17), (-0.27, 0.26), (-0.13, 0.32),
        (0.00, 0.35),
        (0.13, 0.32), (0.27, 0.26), (0.44, 0.17),
        (0.62, 0.10), (0.82, 0.06), (1.00, lower_corner_v),
    ]
    lower_outer_n = [
        (-1.00, lower_corner_v), (-0.92, 0.20), (-0.80, 0.42),
        (-0.64, 0.66), (-0.47, 0.85), (-0.28, 0.99),
        (0.00, 1.06),
        (0.28, 0.99), (0.47, 0.85), (0.64, 0.66),
        (0.80, 0.42), (0.92, 0.20), (1.00, lower_corner_v),
    ]

    def contour(
        normalized: list[tuple[float, float]],
        height: float,
        inner: int = 0,
        outer_motion: int = 0,
    ) -> list[tuple[float, float]]:
        raw: list[tuple[float, float]] = []
        for u, v in normalized:
            x = CX + pose.shift_x + u * half
            y = CY + v * height
            aperture = max(0.0, 1.0 - u * u) ** (0.62 + 0.48 * pose.pucker)
            if inner < 0:
                y -= opening * 0.46 * aperture
            elif inner > 0:
                y += opening * 0.54 * aperture
            # Inner edges expose the aperture; outer edges show the actual facial
            # motion. The lower lip descends with the jaw much more than the upper
            # lip lifts, so the total mouth height visibly grows during speech.
            if outer_motion < 0:
                y -= upper_lift * aperture
            elif outer_motion > 0:
                y += jaw_drop * aperture
            # Corners participate in expression; the middle keeps its soft mass.
            y -= 4.2 * pose.smile * (abs(u) ** 1.8)
            y += 2.4 * pose.tilt * u
            raw.append((x, y))
        return chaikin(raw)

    upper_outer = contour(upper_outer_n, upper_h, outer_motion=-1)
    upper_inner = contour(upper_inner_n, upper_h, inner=-1)
    lower_inner = contour(lower_inner_n, lower_h, inner=1)
    lower_outer = contour(lower_outer_n, lower_h, outer_motion=1)

    upper_image = Image.new("1", (W, H), 0)
    lower_image = Image.new("1", (W, H), 0)
    ImageDraw.Draw(upper_image).polygon(
        [(round(x), round(y)) for x, y in upper_outer + list(reversed(upper_inner))],
        fill=1,
    )
    ImageDraw.Draw(lower_image).polygon(
        [(round(x), round(y)) for x, y in lower_inner + list(reversed(lower_outer))],
        fill=1,
    )

    upper = np.asarray(upper_image, dtype=np.uint8)
    lower = np.asarray(lower_image, dtype=np.uint8)
    mask = np.maximum(upper, lower)
    region = np.zeros((H, W), dtype=np.int8)
    region[upper != 0] = -1
    region[lower != 0] = 1
    return mask, region


def digital_cell_style(mask: np.ndarray, pose: Pose) -> np.ndarray:
    """Render young, clean 2x2 luminous cells separated by regular 1px gutters."""
    styled = np.zeros((H, W), dtype=np.uint8)
    # The reference artwork contains about forty cells across the mouth. On this
    # display, a 3px pitch recreates that scale: a square 2x2 light with a 1px gap.
    for y in range(1, H - 1, 3):
        for x in range(0, W - 1, 3):
            sample_y = min(H - 1, y + 1)
            sample_x = min(W - 1, x + 1)
            if mask[sample_y, sample_x]:
                styled[y : y + 2, x : x + 2] = 1

    # A smooth vector curve can occasionally quantize to a single terminal OLED
    # cell. Do not widen it into the old three-cell block; instead, remove only
    # an isolated last cell when the row directly above proves there is a wider
    # connected lip body. Two-cell and wider natural endings are left untouched.
    upper_h, _ = lip_mass_heights(pose)
    bead_v, _, _ = upper_lip_dynamics(pose)
    bead_edge_y = (
        CY
        + bead_v * upper_h
        - OPENING_SCALE * pose.openness * 0.46
    )
    bead_center_x = CX + pose.shift_x
    central_columns = [
        x
        for x in range(0, W - 1, 3)
        if abs((x + 0.5) - bead_center_x) <= 10.0
    ]
    candidate_rows = [
        y
        for y in range(1, H - 1, 3)
        if bead_edge_y - 8.0 <= y <= bead_edge_y + 1.5
    ]
    for y in reversed(candidate_rows):
        occupied = [
            x
            for x in central_columns
            if styled[y : y + 2, x : x + 2].any()
        ]
        if not occupied:
            continue
        if len(occupied) == 1 and y >= 4:
            tip_x = occupied[0]
            above = [
                x
                for x in central_columns
                if styled[y - 3 : y - 1, x : x + 2].any()
                and abs(x - tip_x) <= 6
            ]
            if len(above) >= 2:
                styled[y : y + 2, tip_x : tip_x + 2] = 0
        break

    # Anatomical invariant: transverse stretch cannot tear the mouth corners.
    # Reinforce the shared corner cells after coarse 3px grid sampling. Narrow
    # open/round families are intentionally excluded so vertical opening may
    # produce the dramatic separated-corner silhouette seen in the reference.
    if requires_connected_corners(pose):
        half = BASE_HALF_WIDTH * pose.width
        for direction in (-1, 1):
            corner_x = CX + pose.shift_x + direction * half
            corner_y = CY - 4.2 * pose.smile + 2.4 * pose.tilt * direction
            cell_x = 3 * round(corner_x / 3)
            cell_y = 1 + 3 * round((corner_y - 1) / 3)
            cell_x = max(0, min(W - 2, cell_x))
            cell_y = max(1, min(H - 3, cell_y))
            for x in (cell_x, cell_x - direction * 3):
                x = max(0, min(W - 2, x))
                styled[cell_y : cell_y + 2, x : x + 2] = 1
    return styled


def make_frame(pose: Pose) -> np.ndarray:
    mask, _ = build_solid_lips(pose)
    return digital_cell_style(mask, pose)


def pack_gfx_bitmap(frame: np.ndarray) -> np.ndarray:
    """Adafruit_GFX drawBitmap uses row-major, MSB-first packed bits."""
    return np.packbits(frame.astype(np.uint8), axis=1, bitorder="big").reshape(-1)


def write_header(frames: list[np.ndarray]) -> Path:
    path = OUTPUT_DIR / "lip_frames.h"
    lines = [
        "#pragma once",
        "",
        "// Lilyput chest lips: 梦露嘴唇 / Marilyn lips named release.",
        "// Generated by make_lips.py. 128x64, Adafruit_GFX MSB-first bitmap data.",
        f"#define NUM_LIP_FRAMES {len(frames)}",
        "",
    ]
    for index, pose in enumerate(POSES):
        lines.append(f"#define LIP_{pose.key} {index}")
    lines.extend(
        (
            "",
            "static const unsigned char PROGMEM "
            "LIP_FRAMES[NUM_LIP_FRAMES][1024] = {",
        )
    )

    for index, (pose, frame) in enumerate(zip(POSES, frames)):
        data = pack_gfx_bitmap(frame)
        lines.append(f"  {{  // {index}: {pose.key}")
        for start in range(0, len(data), 16):
            chunk = data[start : start + 16]
            values = ",".join(f"0x{int(value):02X}" for value in chunk)
            lines.append(f"    {values},")
        lines.append("  },")
    lines.extend(("};", ""))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def oled_preview(frame: np.ndarray, scale: int = 5) -> Image.Image:
    """Nearest-neighbour blue-on-black preview of the actual one-bit pixels."""
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[frame != 0] = (12, 86, 255)
    image = Image.fromarray(rgb, mode="RGB")
    return image.resize((W * scale, H * scale), Image.Resampling.NEAREST)


def write_contact_sheet(frames: list[np.ndarray]) -> Path:
    scale = 4
    tile_w, tile_h = W * scale, H * scale
    cols = 3
    rows = (len(frames) + cols - 1) // cols
    pad, label_h = 18, 22
    sheet = Image.new(
        "RGB",
        (
            pad + cols * (tile_w + pad),
            pad + rows * (tile_h + label_h + pad),
        ),
        (10, 11, 16),
    )
    draw = ImageDraw.Draw(sheet)
    for index, (pose, frame) in enumerate(zip(POSES, frames)):
        col, row = index % cols, index // cols
        x = pad + col * (tile_w + pad)
        y = pad + row * (tile_h + label_h + pad)
        sheet.paste(oled_preview(frame, scale), (x, y + label_h))
        draw.text((x, y + 2), f"{index:02d} {pose.key}", fill=(125, 160, 230))
    path = OUTPUT_DIR / "梦露嘴唇_静态预览.png"
    sheet.save(path)
    return path


def write_demo_gif(frames: list[np.ndarray]) -> Path:
    # Four legal syllables. Intermediate frames are actual geometric muscle
    # stages, so each family moves through five adjacent shapes.
    key_to_index = {pose.key: index for index, pose in enumerate(POSES)}
    sequence_keys = (
        # Open family: closure -> onset -> open vowel -> release.
        "REST", "PRESS", "SOFT", "PART", "OPEN_RISE_1", "AH",
        "OPEN_RISE_2", "DEEP_AH", "SCREAM_CROP", "DEEP_AH", "OPEN_RISE_2", "AH",
        "OPEN_RISE_1", "PART", "SOFT", "PRESS", "REST",
        # Wide family: no jump from smile directly into a pucker.
        "REST", "SOFT", "WIDE_RISE_1", "PART", "WIDE_RISE_2",
        "WIDE_E", "WIDE_CROP", "WIDE_E", "WIDE_RISE_2", "PART", "WIDE_RISE_1", "SOFT",
        "PRESS", "REST",
        # Round family: compression precedes protrusion.
        "REST", "PRESS", "ROUND_RISE_1", "OO", "ROUND_RISE_2",
        "OH", "ROUND_CROP", "OH", "ROUND_RISE_2", "OO", "ROUND_RISE_1", "PRESS", "REST",
        # Soft asymmetric family: one coherent side-pull gesture.
        "REST", "SOFT", "SIDE_L_RISE_1", "ASYM_L", "SIDE_L_RISE_2",
        "BREATH", "SIDE_L_CROP", "BREATH", "SIDE_L_RISE_2", "ASYM_L", "SIDE_L_RISE_1",
        "SOFT", "PRESS", "REST",
    )
    sequence = tuple(key_to_index[key] for key in sequence_keys)
    # Small equal muscle steps; closures and peak vowels receive a little weight.
    durations = tuple(
        130 if key == "REST" else
        112 if key.endswith("_CROP") else
        92 if key in ("DEEP_AH", "WIDE_E", "OH", "BREATH") else
        58
        for key in sequence_keys
    )
    images = [oled_preview(frames[index], scale=6) for index in sequence]
    path = OUTPUT_DIR / "梦露嘴唇_动态预览.gif"
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=list(durations),
        loop=0,
        optimize=False,
        disposal=2,
    )
    return path


def main() -> None:
    # Design invariant from real oral musculature: no sixth-stage pose may
    # maximize both dimensions. Each family intensifies along its own axis and
    # yields along the antagonist axis.
    assert POSES[22].openness > BASE_POSES[11].openness
    assert POSES[22].width < BASE_POSES[11].width
    assert POSES[23].width >= BASE_POSES[4].width
    assert POSES[23].openness < BASE_POSES[4].openness
    assert POSES[24].openness > BASE_POSES[6].openness
    assert POSES[24].width < BASE_POSES[6].width
    assert POSES[25].openness < BASE_POSES[8].openness
    assert POSES[26].openness < BASE_POSES[8].openness
    assert max(pose.width for pose in POSES) <= 1.18
    frames = [make_frame(pose) for pose in POSES]
    header = write_header(frames)
    preview = write_contact_sheet(frames)
    animation = write_demo_gif(frames)
    print(f"poses={len(frames)}")
    print(f"header={header}")
    print(f"preview={preview}")
    print(f"animation={animation}")
    for index, (pose, frame) in enumerate(zip(POSES, frames)):
        print(f"{index:02d} {pose.key:8s} lit_pixels={int(frame.sum())}")


if __name__ == "__main__":
    main()
