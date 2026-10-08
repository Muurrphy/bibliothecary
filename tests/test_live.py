"""The realtime path against a fake realtime server (needs the `websockets` package for the fake)."""

import json
import threading
import time

import pytest

from margin import brain
from margin.bus import Bus
from margin.lesson import Lesson
from margin.live import Ears, RealtimeLink
from margin.player import Player

websockets_sync = pytest.importorskip("websockets.sync.server")

from test_margin import EXAMPLE, QuickVoice, _wait_for

ANSWER = {"then": "continue", "steps": [{"say": "第一句短回答。", "focus": "p2.s1"}, {"say": "第二句细节。"}]}


def fake_realtime(transcript: str, answer: dict, seen: dict):
    def handler(ws):
        for raw in ws:
            ev = json.loads(raw)
            kind = ev["type"]
            seen.setdefault(kind, 0)
            seen[kind] += 1
            if kind == "session.update":
                seen["session"] = ev["session"]
                ws.send(json.dumps({"type": "session.updated"}))
            elif kind == "input_audio_buffer.commit":
                ws.send(json.dumps({"type": "input_audio_buffer.committed", "item_id": "item_1"}))
            elif kind == "response.create":
                seen["instructions"] = ev["response"]["instructions"]
                rid = "resp_1"
                ws.send(json.dumps({"type": "response.created", "response": {"id": rid, "metadata": ev["response"]["metadata"]}}))
                time.sleep(0.05)
                ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed",
                                    "item_id": "item_1", "transcript": transcript}))
                text = json.dumps(answer, ensure_ascii=False)
                for i in range(0, len(text), 9):
                    ws.send(json.dumps({"type": "response.output_text.delta", "response_id": rid, "delta": text[i:i + 9]}))
                    time.sleep(0.01)
                ws.send(json.dumps({"type": "response.done", "response": {"id": rid, "status": "completed"}}))
            elif kind == "response.cancel":
                ws.send(json.dumps({"type": "response.done", "response": {"id": "resp_1", "status": "cancelled"}}))
    server = websockets_sync.serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"ws://127.0.0.1:{server.socket.getsockname()[1]}/v1/realtime"


def _setup(transcript, recent=(), lesson_path=EXAMPLE):
    seen: dict = {}
    server, url = fake_realtime(transcript, ANSWER, seen)
    bus, voice = Bus(), QuickVoice()
    lesson = Lesson.load(lesson_path)
    player = Player(bus, voice)
    player.forced = brain.forced_answer
    player.load(lesson)
    link = RealtimeLink("sk-test", log=lambda m: None, url=url)
    assert link.connected.wait(5)
    echo = lambda text: any(text in r for r in recent)
    ears = Ears(player, link, None, echo, lambda: "INSTRUCTIONS", lambda m: None)
    return server, seen, voice, lesson, ears, bus, link


def test_spoken_question_streams_to_the_realtime_model_and_is_answered():
    server, seen, voice, lesson, ears, bus, link = _setup("那什么隐性基因会导致耳聋？")
    try:
        assert seen["session"]["output_modalities"] == ["text"]
        for _ in range(3):
            ears.audio("q1", b"\x00\x01" * 2400)
        out = ears.end("q1")
        assert out["live"] is True
        assert _wait_for(lambda: lesson.steps[0].say in voice.said)
        assert voice.said[:2] == ["第一句短回答。", "第二句细节。"]
        assert seen["input_audio_buffer.append"] == 3 and seen["instructions"] == "INSTRUCTIONS"
        assert bus.screen()["screen"]["status"] == "reading"
    finally:
        link.close()
        server.shutdown()


def test_its_own_voice_is_ignored():
    line = Lesson.load(EXAMPLE).steps[1].say
    server, seen, voice, _lesson, ears, bus, link = _setup(line[:20], recent=[line])
    try:
        ears.audio("q2", b"\x00\x01" * 2400)
        ears.end("q2")
        assert _wait_for(lambda: seen.get("response.cancel"))     # the answer is called off
        time.sleep(0.3)
        assert "第一句短回答。" not in voice.said
        assert bus.screen()["screen"]["status"] == "paused"        # and nothing else changes
    finally:
        link.close()
        server.shutdown()


def test_a_planned_moment_wins_over_the_model_and_sends_its_cue():
    octopus = EXAMPLE.parent / "octopus.lesson.json"
    server, _seen, voice, _lesson, ears, bus, link = _setup("章鱼睡觉是什么样子？", lesson_path=octopus)
    try:
        ears.audio("q3", b"\x00\x01" * 2400)
        ears.end("q3")
        assert _wait_for(lambda: "你看，这就是章鱼睡觉的样子。" in voice.said)
        assert "第一句短回答。" not in voice.said
        cues = [e["data"] for e in bus.since(0, timeout=0)["events"] if e["kind"] == "cue"]
        assert cues and cues[0]["name"] == "octopus_video"
    finally:
        link.close()
        server.shutdown()


def test_a_spoken_command_is_done_at_once_without_the_model():
    server, seen, voice, lesson, ears, _bus, link = _setup("你繼續講")   # traditional characters, too
    try:
        ears.audio("q4", b"\x00\x01" * 2400)
        ears.end("q4")
        assert _wait_for(lambda: lesson.steps[0].say in voice.said)        # straight back to the plan
        assert _wait_for(lambda: seen.get("response.cancel"))
        assert "第一句短回答。" not in voice.said
    finally:
        link.close()
        server.shutdown()


def test_a_stalled_realtime_answer_is_asked_again_the_classic_way(monkeypatch):
    monkeypatch.setenv("MARGIN_FIRST_TEXT_TIMEOUT", "0.3")
    seen: dict = {}

    def handler(ws):                       # accepts the question, then never answers
        for raw in ws:
            ev = json.loads(raw)
            seen[ev["type"]] = seen.get(ev["type"], 0) + 1
            if ev["type"] == "session.update":
                ws.send(json.dumps({"type": "session.updated"}))
            elif ev["type"] == "input_audio_buffer.commit":
                ws.send(json.dumps({"type": "input_audio_buffer.committed", "item_id": "item_9"}))

    server = websockets_sync.serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"ws://127.0.0.1:{server.socket.getsockname()[1]}/v1/realtime"
    from margin.lesson import Step

    bus, voice = Bus(), QuickVoice()
    asked = []

    def answerer(lesson, question, current, position=None, history=None):
        asked.append(question)
        return {"steps": [Step(say="经典路径的回答。")], "then": "pause"}

    player = Player(bus, voice, answerer)
    player.load(Lesson.load(EXAMPLE))
    link = RealtimeLink("sk-test", log=lambda m: None, url=url)
    try:
        assert link.connected.wait(5)
        ears = Ears(player, link, lambda audio, mime: "以色列在哪里？", lambda t: False,
                    lambda: "INSTRUCTIONS", lambda m: None)
        ears.audio("q5", b"\x00\x01" * 2400)
        ears.end("q5")
        assert _wait_for(lambda: "经典路径的回答。" in voice.said, timeout=6)
        assert asked == ["以色列在哪里？"]
    finally:
        link.close()
        server.shutdown()
