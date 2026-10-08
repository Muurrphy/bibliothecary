#!/usr/bin/env python3
"""Generate the first English Mouth v2 muscle preview.

This experiment deliberately lives outside the live runtime.  It reuses the
approved Mouth raster style, but drives it through a richer, display-neutral
muscle model and a small coarticulated English phrase.  It never writes current
firmware files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import csv
import importlib.util
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE / "make_lips.py"
FPS = 20


def _load_legacy_generator():
    spec = importlib.util.spec_from_file_location("lilyput_mouth_v1", LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载当前口型生成器：{LEGACY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = _load_legacy_generator()


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class MusclePose:
    key: str
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


CHANNELS = tuple(
    field.name for field in fields(MusclePose) if field.name != "key"
)


def constrain(pose: MusclePose, *, key: str | None = None) -> MusclePose:
    """Apply the muscle antagonism and closure invariants from user review."""
    jaw = clamp(pose.jaw_open)
    separation = clamp(pose.lip_separation)
    width = clamp(pose.mouth_width)
    press = clamp(pose.lip_press)
    roundness = clamp(pose.lip_round)
    protrusion = clamp(pose.lip_protrusion)

    # A deep jaw opening pulls the corners inward.  A strong transverse pull
    # limits jaw drop.  These limits act on semantic channels before rendering.
    if jaw > 0.52:
        width = min(width, 0.72 - 0.42 * ((jaw - 0.52) / 0.48))
    if width > 0.72:
        jaw = min(jaw, 0.48 - 0.24 * ((width - 0.72) / 0.28))

    # Lip compression owns the aperture.  Neighboring vowels may anticipate,
    # but cannot erase the visible M/B/P seal.
    closure = 1.0 - 0.96 * press
    separation *= closure
    jaw *= 1.0 - 0.80 * press

    # Round/protruded lips contract horizontally instead of expanding on every
    # axis.  This is deliberately mild; the renderer applies a second limit.
    width = min(width, 1.0 - 0.32 * roundness - 0.16 * protrusion)

    return MusclePose(
        key=key or pose.key,
        jaw_open=clamp(jaw),
        lip_separation=clamp(separation),
        mouth_width=clamp(width),
        lip_round=roundness,
        lip_protrusion=protrusion,
        upper_lip_raise=clamp(pose.upper_lip_raise),
        lower_lip_depress=clamp(pose.lower_lip_depress),
        lip_press=press,
        lower_lip_tuck=clamp(pose.lower_lip_tuck),
        corner_raise=clamp(pose.corner_raise, -1.0, 1.0),
        asymmetry=clamp(pose.asymmetry, -1.0, 1.0),
    )


TARGETS = {
    pose.key: constrain(pose)
    for pose in (
        MusclePose("REST", lip_separation=0.035, lip_press=0.12),
        MusclePose(
            "PRESS_MBP", mouth_width=0.46, lip_round=0.14,
            lip_protrusion=0.10, lip_press=1.0,
        ),
        MusclePose(
            "FV_TUCK", jaw_open=0.10, lip_separation=0.15,
            mouth_width=0.57, upper_lip_raise=0.18,
            lower_lip_tuck=1.0, asymmetry=-0.05,
        ),
        MusclePose(
            "TH_DH", jaw_open=0.14, lip_separation=0.22,
            mouth_width=0.59, upper_lip_raise=0.12,
            lower_lip_depress=0.10,
        ),
        MusclePose(
            "SOFT", jaw_open=0.15, lip_separation=0.22,
            mouth_width=0.53,
        ),
        MusclePose(
            "WIDE_I", jaw_open=0.24, lip_separation=0.31,
            mouth_width=0.96, upper_lip_raise=0.13, corner_raise=0.20,
        ),
        MusclePose(
            "MID_E", jaw_open=0.34, lip_separation=0.43,
            mouth_width=0.82, upper_lip_raise=0.17, corner_raise=0.10,
        ),
        MusclePose(
            "OPEN_AE", jaw_open=0.64, lip_separation=0.72,
            mouth_width=0.60, upper_lip_raise=0.28,
            lower_lip_depress=0.52,
        ),
        MusclePose(
            "OPEN_AH", jaw_open=0.76, lip_separation=0.82,
            mouth_width=0.52, upper_lip_raise=0.31,
            lower_lip_depress=0.68,
        ),
        MusclePose(
            "DEEP_AA", jaw_open=1.0, lip_separation=0.96,
            mouth_width=0.34, upper_lip_raise=0.50,
            lower_lip_depress=1.0,
        ),
        MusclePose(
            "ROUND_AO", jaw_open=0.66, lip_separation=0.72,
            mouth_width=0.36, lip_round=0.88, lip_protrusion=0.40,
            upper_lip_raise=0.25, lower_lip_depress=0.60,
        ),
        MusclePose(
            "ROUND_OW", jaw_open=0.45, lip_separation=0.52,
            mouth_width=0.31, lip_round=0.90, lip_protrusion=0.62,
            lower_lip_depress=0.30,
        ),
        MusclePose(
            "PUCKER_UW", jaw_open=0.25, lip_separation=0.36,
            mouth_width=0.18, lip_round=1.0, lip_protrusion=1.0,
        ),
        MusclePose(
            "RHOTIC_ER", jaw_open=0.30, lip_separation=0.38,
            mouth_width=0.29, lip_round=0.58, lip_protrusion=0.68,
            asymmetry=0.05,
        ),
        MusclePose(
            "BREATH_H", jaw_open=0.48, lip_separation=0.62,
            mouth_width=0.55, upper_lip_raise=0.28,
            lower_lip_depress=0.36, asymmetry=0.04,
        ),
        MusclePose(
            "SIDE_L", jaw_open=0.26, lip_separation=0.31,
            mouth_width=0.68, upper_lip_raise=0.14,
            corner_raise=0.10, asymmetry=-0.34,
        ),
        MusclePose(
            "SIDE_SH", jaw_open=0.29, lip_separation=0.35,
            mouth_width=0.48, lip_round=0.34, lip_protrusion=0.25,
            upper_lip_raise=0.19, asymmetry=0.20,
        ),
    )
}


def blend(key: str, poses: list[tuple[MusclePose, float]]) -> MusclePose:
    total = sum(weight for _, weight in poses)
    if total <= 0:
        return TARGETS["REST"]
    values = {}
    for channel in CHANNELS:
        values[channel] = sum(
            getattr(pose, channel) * weight for pose, weight in poses
        ) / total
    return constrain(MusclePose(key=key, **values))


def _shift_layer(mask: np.ndarray, dy: int) -> np.ndarray:
    shifted = np.zeros_like(mask)
    if dy == 0:
        return mask.copy()
    if dy > 0:
        shifted[dy:] = mask[:-dy]
    else:
        shifted[:dy] = mask[-dy:]
    return shifted


def _tuck_lower_lip(mask: np.ndarray, amount: float) -> np.ndarray:
    """Lift and slightly compress the central lower lip for F/V."""
    if amount <= 0.01:
        return mask
    result = np.zeros_like(mask)
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs):
        center = max(0.0, 1.0 - abs(x - LEGACY.CX) / 42.0)
        new_y = int(round(y - 3.2 * amount * center))
        if 0 <= new_y < LEGACY.H:
            result[new_y, x] = 1
    return result


def legacy_pose(pose: MusclePose):
    pose = constrain(pose)
    openness = clamp(
        0.98 * pose.jaw_open + 0.54 * pose.lip_separation,
        0.0,
        1.76,
    )
    width = (
        0.74
        + 0.48 * pose.mouth_width
        - 0.10 * pose.lip_round
        - 0.10 * pose.lip_protrusion
        - 0.08 * pose.jaw_open
    )
    width = clamp(width, 0.58, 1.18)
    pucker = clamp(
        0.88 * pose.lip_round + 0.58 * pose.lip_protrusion,
        0.0,
        1.40,
    )
    return LEGACY.Pose(
        key=pose.key,
        openness=openness,
        width=width,
        pucker=pucker,
        smile=0.88 * pose.corner_raise,
        tilt=2.6 * pose.asymmetry,
        shift_x=2.0 * pose.asymmetry,
        upper_bias=1.1 * pose.upper_lip_raise - 0.25 * pose.lip_press,
        lower_bias=(
            1.2 * pose.lower_lip_depress
            - 0.45 * pose.lower_lip_tuck
        ),
    )


def render_frame(pose: MusclePose) -> np.ndarray:
    """Render one v2 pose with independent upper/lower vertical motion."""
    pose = constrain(pose)
    legacy = legacy_pose(pose)
    _, region = LEGACY.build_solid_lips(legacy)
    upper = (region < 0).astype(np.uint8)
    lower = (region > 0).astype(np.uint8)

    upper = _shift_layer(
        upper,
        int(round(-2.4 * pose.upper_lip_raise + 1.8 * pose.lip_press)),
    )
    lower = _tuck_lower_lip(lower, pose.lower_lip_tuck)
    lower = _shift_layer(
        lower,
        int(round(
            2.4 * pose.lower_lip_depress
            + 1.6 * pose.jaw_open
            - 2.4 * pose.lip_press
        )),
    )
    mask = np.maximum(upper, lower)
    return LEGACY.digital_cell_style(mask, legacy)


def preview(frame: np.ndarray, scale: int = 4) -> Image.Image:
    rgb = np.zeros((LEGACY.H, LEGACY.W, 3), dtype=np.uint8)
    rgb[frame != 0] = (10, 92, 255)
    return Image.fromarray(rgb, mode="RGB").resize(
        (LEGACY.W * scale, LEGACY.H * scale),
        Image.Resampling.NEAREST,
    )


def write_contact_sheet() -> Path:
    poses = list(TARGETS.values())
    scale = 4
    tile_w, tile_h = LEGACY.W * scale, LEGACY.H * scale
    cols = 3
    rows = math.ceil(len(poses) / cols)
    pad, label_h = 16, 24
    sheet = Image.new(
        "RGB",
        (
            pad + cols * (tile_w + pad),
            pad + rows * (tile_h + label_h + pad),
        ),
        (7, 8, 13),
    )
    draw = ImageDraw.Draw(sheet)
    for index, pose in enumerate(poses):
        col, row = index % cols, index // cols
        x = pad + col * (tile_w + pad)
        y = pad + row * (tile_h + label_h + pad)
        draw.text((x, y + 3), f"{index:02d} {pose.key}", fill=(120, 165, 245))
        sheet.paste(preview(render_frame(pose), scale), (x, y + label_h))
    path = HERE / "英文_v2_第一版_静态目标.png"
    sheet.save(path)
    return path


@dataclass(frozen=True)
class Phone:
    symbol: str
    target: str
    duration_ms: int
    strength: float = 1.0


# A hand-checked preview sentence, chosen to expose closure, labiodental tuck,
# open/round diphthongs, wide vowels, rhotic rounding and consonant clusters.
SENTENCE = "Please watch my voice become beautifully alive."
PHONES = (
    Phone("P", "PRESS_MBP", 85),
    Phone("L", "SIDE_L", 65),
    Phone("IY", "WIDE_I", 150, 1.05),
    Phone("Z", "SIDE_L", 65),
    Phone("W", "PUCKER_UW", 80),
    Phone("AA", "DEEP_AA", 155, 1.10),
    Phone("CH", "SIDE_SH", 80),
    Phone("M", "PRESS_MBP", 80),
    Phone("AY:a", "OPEN_AH", 85),
    Phone("AY:i", "WIDE_I", 90),
    Phone("V", "FV_TUCK", 75),
    Phone("OY:o", "ROUND_AO", 95),
    Phone("OY:i", "WIDE_I", 95),
    Phone("S", "SIDE_L", 65),
    Phone("B", "PRESS_MBP", 80),
    Phone("IH", "MID_E", 80),
    Phone("K", "SOFT", 55),
    Phone("AH", "OPEN_AH", 90),
    Phone("M", "PRESS_MBP", 75),
    Phone("B", "PRESS_MBP", 70),
    Phone("Y", "WIDE_I", 55),
    Phone("UW", "PUCKER_UW", 130, 1.05),
    Phone("T", "SOFT", 50),
    Phone("AH", "OPEN_AH", 70),
    Phone("F", "FV_TUCK", 70),
    Phone("AH", "OPEN_AH", 70),
    Phone("L", "SIDE_L", 55),
    Phone("IY", "WIDE_I", 115),
    Phone("AH", "OPEN_AH", 65),
    Phone("L", "SIDE_L", 55),
    Phone("AY:a", "OPEN_AH", 90, 1.08),
    Phone("AY:i", "WIDE_I", 95, 1.08),
    Phone("V", "FV_TUCK", 70),
)


def phone_spans() -> list[tuple[Phone, int, int]]:
    spans = []
    cursor = 260
    for phone in PHONES:
        spans.append((phone, cursor, cursor + phone.duration_ms))
        cursor += phone.duration_ms
    return spans


def dominance(t_ms: float, start: int, end: int, target: str) -> float:
    """Asymmetric preparation/release window for visible coarticulation."""
    # Rounded and closed gestures are prepared a little earlier than neutral
    # consonants.  Release is shorter so the next target can take over.
    lead = 105.0 if target in {"PRESS_MBP", "PUCKER_UW", "ROUND_AO"} else 75.0
    trail = 60.0 if target == "PRESS_MBP" else 85.0
    if start <= t_ms <= end:
        return 1.0
    if start - lead <= t_ms < start:
        phase = (t_ms - (start - lead)) / lead
        return phase * phase * (3.0 - 2.0 * phase)
    if end < t_ms <= end + trail:
        phase = 1.0 - (t_ms - end) / trail
        return phase * phase * (3.0 - 2.0 * phase)
    return 0.0


def pose_at(t_ms: float, spans: list[tuple[Phone, int, int]]) -> MusclePose:
    weighted: list[tuple[MusclePose, float]] = [(TARGETS["REST"], 0.22)]
    active_press = False
    for phone, start, end in spans:
        weight = dominance(t_ms, start, end, phone.target) * phone.strength
        if weight <= 0:
            continue
        weighted.append((TARGETS[phone.target], weight))
        if phone.target == "PRESS_MBP" and start <= t_ms <= end:
            active_press = True
    result = blend("ANIM", weighted)

    # Perceptual resistance: a bilabial closure is categorical to the viewer,
    # not a soft average that can be diluted by the next vowel.
    if active_press:
        result = blend(
            "ANIM_PRESS_LOCK",
            [(result, 0.15), (TARGETS["PRESS_MBP"], 0.85)],
        )
    return result


def write_sentence_gif() -> tuple[Path, Path]:
    spans = phone_spans()
    total_ms = spans[-1][2] + 420
    frame_ms = 1000.0 / FPS
    frames_out: list[Image.Image] = []
    trajectory: list[dict[str, str | int | float]] = []
    previous = TARGETS["REST"]

    for frame_index in range(math.ceil(total_ms / frame_ms)):
        t_ms = frame_index * frame_ms
        raw = pose_at(t_ms, spans)
        # A critically damped-looking one-pole filter removes single-frame
        # jumps.  The protected PRESS lock above still closes in time.
        current = blend("ANIM_SMOOTH", [(previous, 0.28), (raw, 0.72)])
        previous = current
        frames_out.append(preview(render_frame(current), scale=5))
        row: dict[str, str | int | float] = {
            "frame": frame_index,
            "time_ms": round(t_ms, 1),
        }
        row.update({name: round(getattr(current, name), 4) for name in CHANNELS})
        trajectory.append(row)

    gif_path = HERE / "英文_v2_第一版_整句肌肉预览.gif"
    frames_out[0].save(
        gif_path,
        save_all=True,
        append_images=frames_out[1:],
        duration=int(round(frame_ms)),
        loop=0,
        optimize=False,
        disposal=2,
    )

    csv_path = HERE / "英文_v2_第一版_整句动作轨迹.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame", "time_ms", *CHANNELS])
        writer.writeheader()
        writer.writerows(trajectory)
    return gif_path, csv_path


def write_target_csv() -> Path:
    path = HERE / "英文_v2_第一版_目标通道.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["key", *CHANNELS])
        writer.writeheader()
        for pose in TARGETS.values():
            writer.writerow(asdict(pose))
    return path


def main() -> None:
    sheet = write_contact_sheet()
    gif_path, trajectory = write_sentence_gif()
    targets = write_target_csv()
    print(f"sentence={SENTENCE}")
    print(f"targets={len(TARGETS)} channels={len(CHANNELS)} fps={FPS}")
    print(f"contact_sheet={sheet}")
    print(f"animation={gif_path}")
    print(f"trajectory={trajectory}")
    print(f"target_table={targets}")


if __name__ == "__main__":
    main()
