import json

import pytest

from robot_lipsync import (
    AlignmentSpan,
    Articulation,
    IncrementalArticulationCompiler,
    LatencyTrace,
    TimedPhoneme,
    alignment_to_phonemes,
    enforce_constraints,
    mandarin_syllable_phones,
    phonemes_to_articulation,
    spanish_phones,
    spans_from_elevenlabs,
    summarize_traces,
)
from robot_lipsync.backends import (
    SerialTimelineClient,
    encode_count,
    encode_event,
    encode_json_event,
    encode_reset,
    encode_start,
    parse_reply,
)


def test_articulation_rejects_out_of_range_channel():
    with pytest.raises(ValueError):
        Articulation(1.2, 0, 0, 0, 0)


def test_width_and_open_extremes_are_antagonistic():
    result = enforce_constraints(Articulation(1, 1, 1, 0, 0))
    assert result.mouth_width <= 0.33
    assert result.jaw_open <= 1.0


def test_bilabial_closure_is_not_blended_away():
    events = phonemes_to_articulation(
        "turn",
        [
            TimedPhoneme("M", 0, 70, "en"),
            TimedPhoneme("AA1", 70, 180, "en"),
        ],
    )
    assert events[0].viseme == "PRESS"
    assert events[0].articulation.lip_press == 1.0
    assert events[1].articulation.jaw_open > 0.7


def test_diphthong_is_one_moving_target():
    from robot_lipsync import monroe

    for duration in (120, 240):
        events = phonemes_to_articulation("turn", [TimedPhoneme("OW1", 0, duration, "en")])
        assert [event.viseme for event in events] == ["EN_OW"]
    assert monroe.EN_GLIDES["EN_OW"] == ("ROUND_AO", "ROUND_OW")
    # on the OLED a short diphthong shows its readable endpoint
    assert monroe.FRAME_NAMES[events[0].metadata["oled_frame"]] == "V2_ROUND_OW"


def test_english_reduced_vowels_and_spanish_stress():
    from robot_lipsync.phonemes import spanish_phones

    events = phonemes_to_articulation("a", [TimedPhoneme("AH0", 0, 90, "en"), TimedPhoneme("AH1", 90, 150, "en")])
    assert events[0].viseme == "EN_SCHWA" and events[1].viseme == "OPEN_AH"
    assert events[0].articulation.jaw_open < events[1].articulation.jaw_open
    assert spanish_phones("hola") == ("ES_O1", "ES_L", "ES_A")
    assert spanish_phones("cenar")[3] == "ES_A1"


def test_elevenlabs_seconds_alignment_is_scaled():
    spans = spans_from_elevenlabs(
        {
            "characters": ["H", "i"],
            "character_start_times_seconds": [0.0, 0.08],
            "character_end_times_seconds": [0.08, 0.2],
        }
    )
    assert spans[0].duration_ms == 80
    assert spans[1].start_ms == 80
    assert spans[1].duration_ms == pytest.approx(120)


def test_english_letters_group_into_one_word_timeline():
    phones = alignment_to_phonemes(
        [
            AlignmentSpan("m", 0, 40, "en"),
            AlignmentSpan("e", 40, 80, "en"),
        ]
    )
    assert any(phone.symbol.startswith("M") for phone in phones)
    assert sum(phone.duration_ms for phone in phones) == pytest.approx(120)


def test_spanish_uses_bilabial_b_for_b_and_v():
    phones = spanish_phones("vivir", "es")
    assert phones[:3] == ("ES_B", "ES_I", "ES_B")
    assert "ES_F" not in phones


def test_spanish_dialect_tag_controls_seseo_distinction():
    assert spanish_phones("zapato", "es")[0] == "ES_S"
    assert spanish_phones("zapato", "es-ES")[0] == "ES_TH"


def test_spanish_vowels_have_language_specific_targets():
    phones = alignment_to_phonemes(
        [AlignmentSpan(character, index * 60, 60, "es") for index, character in enumerate("puro ")]
    )
    events = phonemes_to_articulation("es-turn", phones)
    assert any(event.viseme == "ES_PUCKER_U" for event in events)
    assert all(event.language == "es" for event in events)


def test_mandarin_syllable_separates_initial_final_and_tone():
    symbols, tone = mandarin_syllable_phones("lü4")
    assert symbols == ("ZH_APICAL", "ZH_V")
    assert tone == 4


def test_mandarin_apical_i_does_not_create_false_wide_vowel():
    symbols, tone = mandarin_syllable_phones("shi1")
    assert symbols == ("ZH_RETROFLEX", "ZH_IR")
    assert tone == 1
    symbols, _ = mandarin_syllable_phones("si4")
    assert symbols == ("ZH_DENTAL", "ZH_IZ")
    from robot_lipsync.planner import SHAPES

    # The apical vowel stays visible but narrower than the true /i/.
    for name in ("ZH_IZ", "ZH_IR"):
        assert SHAPES[name].mouth_width < SHAPES["ZH_I"].mouth_width
    # zh/ch/sh/r and their apical vowel pout forward (吃, 是).
    assert SHAPES["ZH_IR"].lip_protrusion > 0.3 and SHAPES["ZH_RETROFLEX"].lip_protrusion > 0.3


def test_mandarin_phrase_uses_contextual_pinyin():
    phones = alignment_to_phonemes(
        [
            AlignmentSpan("银", 0, 120, "zh-CN"),
            AlignmentSpan("行", 120, 120, "zh-CN"),
        ]
    )
    second_syllable = [phone for phone in phones if phone.start_ms >= 120]
    assert [phone.symbol for phone in second_syllable] == ["ZH_VELAR", "ZH_A", "ZH_NG"]
    assert all(phone.tone == 2 for phone in second_syllable)


def test_mandarin_token_span_is_split_across_characters():
    phones = alignment_to_phonemes([AlignmentSpan("你好", 0, 300, "zh-CN")])
    assert phones
    assert any(phone.start_ms >= 150 for phone in phones)
    assert max(phone.start_ms + phone.duration_ms for phone in phones) == pytest.approx(300)


def test_incremental_compiler_does_not_repeat_events():
    compiler = IncrementalArticulationCompiler("turn")
    first = compiler.append([AlignmentSpan(char, index * 50, 50, "en") for index, char in enumerate("Good ")])
    second = compiler.append([AlignmentSpan(char, 250 + index * 50, 50, "en") for index, char in enumerate("evening ")])
    final = compiler.finish()
    combined = first + second + final
    assert combined
    assert len({(event.start_ms, event.viseme) for event in combined}) == len(combined)


def test_incremental_compiler_withholds_partial_word():
    compiler = IncrementalArticulationCompiler("turn")
    assert compiler.append([AlignmentSpan(char, index * 50, 50, "en") for index, char in enumerate("charmin")]) == []


def test_incremental_mandarin_keeps_two_character_context():
    compiler = IncrementalArticulationCompiler("zh-turn")
    assert compiler.append([AlignmentSpan("银", 0, 120, "zh-CN")]) == []
    assert compiler.append([AlignmentSpan("行", 120, 120, "zh-CN")]) == []
    first = compiler.append([AlignmentSpan("家", 240, 120, "zh-CN")])
    final = compiler.finish()
    assert first
    assert final
    assert all(event.language == "zh-CN" for event in first + final)


def test_compact_serial_backend_is_newline_delimited():
    event = phonemes_to_articulation("turn", [TimedPhoneme("M", 0, 70, "en")])[0]
    payload = encode_json_event(event)
    assert payload.endswith(b"\n")
    decoded = json.loads(payload)
    assert decoded["v"] == 1
    assert len(decoded["a"]) == 8


def test_namespaced_serial_protocol_is_bounded_and_parseable():
    event = phonemes_to_articulation("turn-42", [TimedPhoneme("M", 0, 70, "en")])[0]
    assert encode_reset("turn-42") == b"LIP/RESET turn-42\n"
    assert encode_event(event).startswith(b"LIP/EVENT turn-42 ")
    assert encode_count("turn-42") == b"LIP/COUNT turn-42\n"
    assert encode_start("turn-42", delay_ms=120) == b"LIP/START turn-42 120 0\n"
    assert parse_reply("ERR head_not_armed") is None
    reply = parse_reply("LIP/OK COUNT sid=turn-42 events=9 capacity=256")
    assert reply is not None
    assert reply.name == "COUNT"
    assert reply.fields["events"] == "9"


def test_serial_client_ignores_unrelated_shared_link_errors():
    class FakeStream:
        def __init__(self):
            self.writes = []
            self.replies = [b"ERR head_not_armed\n", b"LIP/OK RESET sid=turn-42 capacity=256\n"]

        def write(self, payload):
            self.writes.append(payload)

        def flush(self):
            pass

        def readline(self):
            return self.replies.pop(0) if self.replies else b""

    stream = FakeStream()
    client = SerialTimelineClient(stream, timeout_s=0.1)
    assert client.reset("turn-42") == 256
    assert stream.writes == [b"LIP/RESET turn-42\n"]


def test_latency_trace_preserves_first_mark_and_counters():
    trace = LatencyTrace(origin=10, session_id="known")
    trace.mark("physical_audio_start", at=11.9)
    trace.mark("physical_audio_start", at=12.5)
    trace.count("underruns", 2)
    assert trace.elapsed_ms("physical_audio_start") == pytest.approx(1900)
    assert trace.to_dict()["counters"]["underruns"] == 2


def test_latency_summary_reports_long_tail():
    records = [{"milliseconds": {"physical_audio_start": value}} for value in (1900, 2000, 2100, 4500)]
    summary = summarize_traces(records)
    assert summary["samples"] == 4
    assert summary["p95_ms"] > 4000


def test_mandarin_finals_follow_surface_pronunciation():
    # "tian" is [tʰiɛn]: mid-open front vowel, then the jaw closes for -n.
    symbols, _ = mandarin_syllable_phones("tian1")
    assert symbols == ("ZH_APICAL", "ZH_YI", "ZH_EH", "ZH_N")
    symbols, _ = mandarin_syllable_phones("hao3")
    assert symbols == ("ZH_VELAR", "ZH_AO")
    symbols, _ = mandarin_syllable_phones("gei3")
    assert symbols == ("ZH_VELAR", "ZH_EI")
    from robot_lipsync.planner import SHAPES

    assert SHAPES["ZH_N"].lip_separation < SHAPES["ZH_EH"].lip_separation


def test_mandarin_initial_keeps_lead_and_final_starts_at_onset():
    from robot_lipsync.planner import phonemes_to_articulation

    phones = alignment_to_phonemes([AlignmentSpan("爸", 1000, 200, "zh-CN")])
    events = phonemes_to_articulation("ba", phones)
    initial, final = events[0], events[1]
    assert initial.viseme == "ZH_BPM" and initial.metadata["syllable_role"] == "initial"
    # initial: 28% of the syllable, shown 42 ms early; final: at its acoustic onset
    assert abs(phones[0].duration_ms - 56.0) < 1e-6
    assert abs(initial.start_ms - (1000 - 42)) < 1e-6
    assert abs(final.start_ms - (1000 + 56)) < 1e-6
    assert initial.articulation.lip_press > 0.9  # closure is never averaged away


def test_mandarin_non_closing_initial_anticipates_rounded_final():
    from robot_lipsync.planner import SHAPES, phonemes_to_articulation

    phones = alignment_to_phonemes([AlignmentSpan("都", 0, 220, "zh-CN")])
    events = phonemes_to_articulation("du", phones)
    assert events[0].viseme == "ZH_APICAL"
    assert events[0].articulation.lip_round > SHAPES["ZH_APICAL"].lip_round + 0.3
