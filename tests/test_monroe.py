import json
import re
from pathlib import Path

from robot_lipsync import monroe
from robot_lipsync.backends.serial_v1 import encode_event
from robot_lipsync.phonemes import AlignmentSpan, alignment_to_phonemes
from robot_lipsync.planner import SHAPES, phonemes_to_articulation

ROOT = Path(__file__).resolve().parents[1]
RENDERERS = ROOT / "src/robot_lipsync/renderers"


def test_frame_bank_matches_the_model():
    header = (ROOT / "firmware/esp32_oled/monroe_frames.h").read_text(encoding="utf-8")
    names = re.findall(r"//\s*\d+:\s*(\S+)", header)
    assert tuple(names) == monroe.FRAME_NAMES
    assert len(re.findall(r"0x[0-9A-F]{2}", header)) == 44 * 1024
    bank = (RENDERERS / "monroe_frames.js").read_text(encoding="utf-8")
    payload = json.loads(bank[bank.index("= {") + 2:bank.rindex("};") + 1])
    assert tuple(payload["names"]) == monroe.FRAME_NAMES


def test_generated_tables_are_in_sync():
    model = (RENDERERS / "monroe_model.js").read_text(encoding="utf-8")
    data = json.loads(model[model.index("= {") + 2:model.rindex("};") + 1])
    assert data["visemeTargets"] == monroe.VISEME_TARGETS
    assert set(data["zhTargets"]) == set(monroe.ZH_TARGETS)
    select = (ROOT / "firmware/esp32_oled/monroe_select.h").read_text(encoding="utf-8")
    assert select.count("},  //") == len(monroe.TARGETS)


def test_every_english_target_picks_its_own_frame():
    for viseme, name in monroe.VISEME_TARGETS.items():
        if name in monroe.TARGETS and viseme in SHAPES and viseme not in {"TH", "ES_ALVEOLAR"}:
            frame = monroe.nearest_frame(monroe.muscle_from_articulation(SHAPES[viseme]))
            assert monroe.FRAME_NAMES[frame] == "V2_" + name, viseme


def test_mandarin_frames_follow_the_chest_table():
    names = monroe.FRAME_NAMES
    assert names[monroe.oled_frame("ZH_BPM")] == "V2_PRESS_MBP"
    assert names[monroe.oled_frame("ZH_RETROFLEX")] == "V2_RHOTIC_ER"
    assert names[monroe.oled_frame("ZH_U")] == "V2_PUCKER_UW"
    assert names[monroe.oled_frame("ZH_A", intensity=0.9, duration_ms=150)] == "V2_OPEN_AH"
    assert names[monroe.oled_frame("ZH_A", intensity=0.7, duration_ms=90)] == "V2_OPEN_AE"


def test_planner_annotates_frames_and_serial_sends_the_hint():
    phones = alignment_to_phonemes([AlignmentSpan("吃", 0, 200, "zh-CN"), AlignmentSpan("谱", 200, 220, "zh-CN")])
    events = phonemes_to_articulation("chi", phones)
    assert all(isinstance(e.metadata["oled_frame"], int) for e in events)
    frames = [monroe.FRAME_NAMES[e.metadata["oled_frame"]] for e in events]
    assert "V2_RHOTIC_ER" in frames and "V2_PRESS_MBP" in frames and "V2_PUCKER_UW" in frames
    line = encode_event(events[0]).decode().split()
    assert len(line) == 14  # LIP/EVENT sid at dur, 9 channels, frame
    assert int(line[-1]) == events[0].metadata["oled_frame"]


def test_rounded_mandarin_targets_pout_and_evert():
    for name in ("ZH_RETROFLEX", "ZH_IR", "ZH_U", "ZH_O"):
        target = monroe.ZH_TARGETS[name]
        assert target.lip_protrusion >= 0.45 and target.upper_lip_raise >= 0.15, name
