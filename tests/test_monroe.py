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


def test_word_level_spans_keep_their_own_timing():
    # edge-tts style: whole words with a pause between the two phrases
    spans = [AlignmentSpan("Hola", 100, 350, "es-ES"), AlignmentSpan("soy", 612, 288, "es-ES"),
             AlignmentSpan("Qué", 2262, 138, "es-ES"), AlignmentSpan("hoy", 2400, 200, "es-ES")]
    phones = alignment_to_phonemes(spans)
    que = [p for p in phones if p.start_ms >= 2262]
    assert [p.symbol for p in que][:2] == ["ES_K", "ES_E1"]
    assert not [p for p in phones if 900 < p.start_ms < 2262]  # silent pause stays silent
    # English word tokens are looked up one by one, not glued into one string
    english = alignment_to_phonemes([AlignmentSpan("What", 0, 240, "en-US"), AlignmentSpan("would", 250, 120, "en-US")])
    assert english[0].symbol == "W" and english[0].start_ms == 0


def test_character_spans_are_still_joined_into_words():
    chars = [AlignmentSpan(c, i * 60, 60, "es") for i, c in enumerate("hola")]
    assert [p.symbol for p in alignment_to_phonemes(chars)] == ["ES_O1", "ES_L", "ES_A"]


def test_spanish_glides_approximants_and_clitics():
    from robot_lipsync.phonemes import spanish_phones

    assert spanish_phones("bueno") == ("ES_B", "ES_W", "ES_E1", "ES_N", "ES_O")
    assert spanish_phones("hoy") == ("ES_O1", "ES_J")
    assert spanish_phones("día") == ("ES_D", "ES_I1", "ES_A")
    assert spanish_phones("la") == ("ES_L", "ES_A")  # function word: no stress
    phones = alignment_to_phonemes([AlignmentSpan("la", 0, 120, "es"), AlignmentSpan("vida", 120, 300, "es"),
                                    AlignmentSpan("un", 600, 100, "es"), AlignmentSpan("beso", 700, 250, "es")])
    symbols = [p.symbol for p in phones]
    assert "ES_BH" in symbols and "ES_B" in symbols  # [β] between vowels, [b] after n
    events = phonemes_to_articulation("es", phones)
    vowel = next(e for e in events if e.metadata["phoneme"] == "ES_I1")
    assert abs(vowel.start_ms - vowel.metadata["audio_start_ms"]) < 0.01  # vowels land on their sound


def test_offset_estimate_finds_early_timestamps():
    from robot_lipsync.calibrate import estimate_offset_ms

    rate = 8000
    samples = [0.0] * rate
    for i in range(int(0.39 * rate), int(0.69 * rate)):  # speech 390-690 ms
        samples[i] = 0.5 if i % 2 else -0.5
    assert estimate_offset_ms([AlignmentSpan("hola", 300, 300, "es")], samples, rate) == 90.0


def test_mandarin_numbers_are_spoken():
    from robot_lipsync.phonemes import spell_mandarin_numbers

    assert spell_mandarin_numbers("10月8日，体感12度") == "十月八日，体感十二度"
    assert spell_mandarin_numbers("7:52出门") == "七点五十二出门"
    assert spell_mandarin_numbers("2026年") == "二零二六年"
    phones = alignment_to_phonemes([AlignmentSpan("12度", 0, 400, "zh-CN")])
    assert len({round(p.start_ms) for p in phones}) >= 5  # 十 二 度, not just 度
