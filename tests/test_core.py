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
    phonemes_to_articulation,
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


def test_short_diphthong_keeps_readable_endpoint():
    events = phonemes_to_articulation("turn", [TimedPhoneme("OW1", 0, 120, "en")])
    assert [event.viseme for event in events] == ["ROUND_OW"]


def test_long_diphthong_preserves_motion_path():
    events = phonemes_to_articulation("turn", [TimedPhoneme("OW1", 0, 240, "en")])
    assert [event.viseme for event in events] == ["ROUND_AO", "ROUND_OW"]


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
