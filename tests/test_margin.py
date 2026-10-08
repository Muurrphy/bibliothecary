import json
import threading
import time
import urllib.request
from pathlib import Path

from margin import brain
from margin.bus import Bus
from margin.lesson import Lesson, Step, split_sentences
from margin.player import Player
from margin.server import App, serve

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "village.lesson.json"


class QuickVoice:
    name = "quick"

    def __init__(self):
        self.said = []

    def speak(self, text, stop):
        self.said.append(text)
        stop.wait(0.01)


class SlowVoice(QuickVoice):
    def speak(self, text, stop):
        self.said.append(text)
        stop.wait(2.0)


def test_split_sentences_keeps_abbreviations_and_chinese():
    assert split_sentences("Dr. Sandler went home. Then she slept!") == ["Dr. Sandler went home.", "Then she slept!"]
    assert split_sentences("今天下雨。带伞！好的") == ["今天下雨。", "带伞！", "好的"]


def test_example_lesson_is_valid():
    lesson = Lesson.load(EXAMPLE)
    assert lesson.problems() == []
    assert lesson.sentence("p3.s2").endswith("the verb comes last.")


def test_bad_steps_are_cleaned():
    lesson = Lesson.load(EXAMPLE)
    steps = brain.clean_steps(lesson, [
        {"focus": "p9.s9", "say": "nowhere"},
        {"focus": "p1.s1", "mark": "not in the sentence", "say": "x"},
        {"focus": "p1.s2", "mark": "3,500", "say": "y"},
    ])
    assert steps[0].focus is None and steps[1].mark is None
    assert steps[2].mark == {"sentence": "p1.s2", "phrase": "3,500"}


def test_scripted_answer_matches_keywords():
    lesson = Lesson.load(EXAMPLE)
    steps = brain.scripted_answer(lesson, "为什么他们的语序跟阿拉伯语不一样？")
    assert steps and steps[0].focus == "p4.s2"
    assert brain.scripted_answer(lesson, "what's the weather") is None


def test_bus_long_poll_wakes_up_and_resets_late_readers():
    bus = Bus()
    out = {}
    t = threading.Thread(target=lambda: out.update(bus.since(0, timeout=2)))
    t.start()
    time.sleep(0.05)
    bus.publish("caption", text="hi")
    t.join(1)
    assert out["events"][0]["data"]["text"] == "hi"
    assert bus.since(1, timeout=0.01)["events"] == []
    assert bus.since(99, timeout=0.01)["reset"] is True  # reader from an older run reloads the screen


def test_player_reads_the_whole_lesson():
    bus, voice = Bus(), QuickVoice()
    player = Player(bus, voice)
    lesson = Lesson.load(EXAMPLE)
    player.load(lesson)
    player.play()
    deadline = time.time() + 5
    while bus.screen()["screen"]["status"] != "done" and time.time() < deadline:
        time.sleep(0.02)
    screen = bus.screen()["screen"]
    assert screen["status"] == "done"
    assert len(voice.said) == len(lesson.steps)
    assert screen["progress"] == [len(lesson.steps), len(lesson.steps)]


def test_question_interrupts_answers_and_resumes():
    bus, voice = Bus(), SlowVoice()
    lesson = Lesson.load(EXAMPLE)
    answers = []

    def answerer(lesson, question, current):
        answers.append((question, current))
        return [Step(say="because", focus="p4.s3", mark={"sentence": "p4.s3", "phrase": "could not hear"})]

    player = Player(bus, voice, answerer)
    player.load(lesson)
    player.play()
    time.sleep(0.2)                       # in the middle of step 1
    player.listening()
    assert bus.screen()["screen"]["status"] == "listening"
    time.sleep(0.2)
    assert len(voice.said) == 1           # it stays quiet while you talk
    player.ask("why?")
    deadline = time.time() + 6
    while time.time() < deadline and "because" not in voice.said:
        time.sleep(0.02)
    time.sleep(0.1)
    screen = bus.screen()["screen"]
    assert answers == [("why?", None)]
    assert screen["focus"] == "p4.s3"
    assert {"sentence": "p4.s3", "phrase": "could not hear"} in screen["marks"]
    assert screen["answer"]["text"] == "because"
    deadline = time.time() + 6
    while time.time() < deadline and lesson.steps[1].say not in voice.said:
        time.sleep(0.02)
    assert lesson.steps[1].say in voice.said            # it goes on with the next line
    assert voice.said.count(lesson.steps[0].say) == 1   # and does not read the interrupted one again


def test_http_api_round_trip():
    bus, voice = Bus(), QuickVoice()
    player = Player(bus, voice, lambda lesson, q, cur: brain.scripted_answer(lesson, q))
    player.load(Lesson.load(EXAMPLE))
    server = serve(App(bus, player), "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "XMLHttpRequest" in page and "=>" not in page   # plain ES5 for old e-reader browsers
        time.sleep(0.1)
        screen = json.loads(urllib.request.urlopen(base + "/api/screen").read())
        assert screen["screen"]["lesson"]["title"] == "A Village Where Everyone Signs"
        req = urllib.request.Request(base + "/api/ask", data=json.dumps({"text": "word order?"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["question"] == "word order?"
        polled = json.loads(urllib.request.urlopen(base + f"/api/poll?since={screen['seq']}&wait=3").read())
        kinds = [e["kind"] for e in polled["events"]]
        assert "status" in kinds or "answer" in kinds
    finally:
        server.shutdown()


def test_elevenlabs_picks_a_v4_model(monkeypatch):
    from margin import speech

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.delenv("MARGIN_ELEVEN_MODEL", raising=False)
    models = [{"model_id": "eleven_multilingual_v2"}, {"model_id": "eleven_v4_turbo"}, {"model_id": "eleven_v4"}]
    monkeypatch.setattr(speech.ElevenLabsVoice, "_request", lambda self, m, p, b=None: json.dumps(models).encode())
    monkeypatch.setattr(speech, "_player", lambda: ["true"])
    assert speech.ElevenLabsVoice("voice").model == "eleven_v4"


def test_elevenlabs_retries_with_basic_settings(monkeypatch):
    import io
    import urllib.error

    from margin import speech

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.setenv("MARGIN_ELEVEN_MODEL", "eleven_v4")
    monkeypatch.setattr(speech, "_player", lambda: ["true"])
    calls = []

    def fake(self, method, path, body=None):
        calls.append(body)
        if len(calls) == 1:
            raise urllib.error.HTTPError(path, 400, "bad", {}, io.BytesIO(b'{"detail": "invalid voice settings"}'))
        return b"mp3"

    monkeypatch.setattr(speech.ElevenLabsVoice, "_request", fake)
    voice = speech.ElevenLabsVoice("voice")
    voice.timestamps = False
    assert voice._synthesize("hi").audio == b"mp3"
    assert set(calls[1]["voice_settings"]) == {"stability", "similarity_boost"}


def test_elevenlabs_gets_timestamps_and_falls_back(monkeypatch):
    import base64
    import io
    import urllib.error

    from margin import speech

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.setenv("MARGIN_ELEVEN_MODEL", "eleven_v4")
    monkeypatch.setattr(speech, "_player", lambda: ["true"])
    alignment = {"characters": ["h", "i"], "character_start_times_seconds": [0, 0.1], "character_end_times_seconds": [0.1, 0.3]}
    reply = json.dumps({"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": alignment}).encode()
    monkeypatch.setattr(speech.ElevenLabsVoice, "_request", lambda self, m, p, b=None: reply)
    clip = speech.ElevenLabsVoice("voice")._synthesize("hi")
    assert clip.audio == b"mp3" and clip.seconds() == 0.3

    def refuse(self, method, path, body=None):
        if "with-timestamps" in path:
            raise urllib.error.HTTPError(path, 422, "no", {}, io.BytesIO(b'{"detail": "timestamps not supported"}'))
        return b"plain"

    monkeypatch.setattr(speech.ElevenLabsVoice, "_request", refuse)
    voice = speech.ElevenLabsVoice("voice")
    assert voice._synthesize("hi").audio == b"plain" and voice.timestamps is False


def test_speaker_page_plays_the_clip_and_reports_back():
    from margin.speaker import Clip, SpeakerHub

    bus = Bus()
    hub = SpeakerHub(bus)
    stop = threading.Event()
    assert hub.play(Clip(b"mp3", "hello"), stop) is False          # nobody listening: play on the computer
    hub.poll_started()
    result = {}
    t = threading.Thread(target=lambda: result.update(ok=hub.play(Clip(b"mp3", "hello"), stop)))
    t.start()
    time.sleep(0.1)
    speak = [e for e in bus.since(0, timeout=0)["events"] if e["kind"] == "speak"][-1]["data"]
    assert hub.clip(speak["id"]).audio == b"mp3" and t.is_alive()   # waits for the page
    hub.finished(speak["id"])
    t.join(1)
    assert result["ok"] is True and not t.is_alive()
    # an interruption hushes the page
    t = threading.Thread(target=lambda: hub.play(Clip(b"mp3", "again"), stop))
    t.start()
    time.sleep(0.1)
    stop.set()
    t.join(1)
    assert bus.since(0, timeout=0)["events"][-1]["kind"] == "hush"


def test_microphone_echo_and_noise_are_ignored():
    bus, voice = Bus(), QuickVoice()
    player = Player(bus, voice)
    heard = {"text": ""}
    app = App(bus, player, transcriber=lambda audio, mime: heard["text"])
    app.hub.recent.append("这个村子里，几乎每个人都会手语。")
    server = serve(app, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def ask_audio(text):
        heard["text"] = text
        req = urllib.request.Request(base + "/api/ask", data=b"RIFF", headers={"Content-Type": "audio/wav"}, method="POST")
        return json.loads(urllib.request.urlopen(req).read())

    try:
        assert "ignored" in ask_audio("几乎每个人都会手语")         # its own voice
        assert "ignored" in ask_audio("谢谢观看")                   # what speech-to-text hears in silence
        assert ask_audio("为什么？")["question"] == "为什么？"       # short real questions get through
        assert ask_audio("他们的语序为什么跟阿拉伯语不一样")["question"].startswith("他们的语序")
    finally:
        server.shutdown()


def test_tablet_page_and_https(tmp_path):
    import shutil
    import ssl

    import pytest

    from margin.tls import ensure_certificate

    if not shutil.which("openssl"):
        pytest.skip("no openssl")
    chain, key, ca = ensure_certificate("127.0.0.1", "", tmp_path)
    bus, voice = Bus(), QuickVoice()
    server = serve(App(bus, Player(bus, voice), ca_file=str(ca)), "127.0.0.1", 0, tls=(chain, key))
    try:
        ctx = ssl.create_default_context(cafile=str(ca))
        url = f"https://127.0.0.1:{server.server_address[1]}"
        page = urllib.request.urlopen(url + "/speaker", context=ctx).read().decode()
        assert "echoCancellation: true" in page and "getUserMedia" in page
        assert urllib.request.urlopen(url + "/margin-ca.crt", context=ctx).read().startswith(b"-----BEGIN CERTIFICATE")
    finally:
        server.shutdown()


def test_commands_need_no_model():
    assert brain.quick_intent("开始吧。") == "continue"
    assert brain.quick_intent("反正你给我继续讲这篇文章吧") == "continue"
    assert brain.quick_intent("等一下") == "pause"
    assert brain.quick_intent("再说一遍") == "back"
    assert brain.quick_intent("为什么？") is None
    assert brain.quick_intent("好吧，继续讲吧，刚才到哪里了？") is None   # a real question: ask the model


def _wait_for(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_after_an_answer_it_goes_back_to_the_plan_even_if_paused():
    bus, voice = Bus(), QuickVoice()
    lesson = Lesson.load(EXAMPLE)
    seen = []

    def answerer(lesson, question, current, position):
        seen.append(position)
        if question == "停":
            return {"steps": [], "then": "pause"}
        return {"steps": [Step(say="answer")], "then": "continue"}

    player = Player(bus, voice, answerer)
    player.load(lesson)                       # paused: nobody pressed play
    player.ask("what is this about?")
    assert _wait_for(lambda: lesson.steps[0].say in voice.said)   # answered, then read on by itself
    assert voice.said[0] == "answer" and seen == [0]
    player.ask("停")
    assert _wait_for(lambda: bus.screen()["screen"]["status"] == "paused")
    n = len(voice.said)
    time.sleep(0.3)
    assert len(voice.said) == n               # and stays quiet when told to


def test_model_answer_carries_what_to_do_next():
    class FakeClient:
        def chat_json(self, system, user, **kw):
            assert "Your plan:" in user and "[NEXT]" in user
            return {"steps": [{"say": "好的", "focus": "p1.s1"}], "then": "PAUSE"}

    lesson = Lesson.load(EXAMPLE)
    out = brain.answer(FakeClient(), lesson, "先停一下，我想想", current=None, position=2)
    assert out["then"] == "pause" and out["steps"][0].focus == "p1.s1"


def test_streamed_answer_speaks_before_the_model_is_done_and_fills_the_wait(monkeypatch):
    monkeypatch.setenv("MARGIN_FILLERS", "1")
    bus, voice = Bus(), QuickVoice()
    voice.prepare = lambda text: None
    lesson = Lesson.load(EXAMPLE)
    written = []

    class SlowClient:
        def chat_json_stream(self, system, user, **kw):
            time.sleep(0.8)                       # slow to start: a filler should cover it
            text = '{"then": "continue", "steps": [{"say": "短答。", "focus": "p4.s2"}, {"say": "细节。"}]}'
            for i in range(0, len(text), 7):
                if "细节" in text[:i] and not written:
                    written.append(list(voice.said))  # what had been said when the 2nd step was still coming
                yield text[i:i + 7]
                time.sleep(0.02)

    player = Player(bus, voice, lambda l, q, c, p: brain.answer_stream(SlowClient(), l, q, current=c, position=p))
    player.load(lesson)
    player.ask("为什么？")
    assert _wait_for(lambda: lesson.steps[0].say in voice.said)
    assert voice.said[0] in ("嗯——", "Hmm—")                    # filled the silence
    assert voice.said[1:3] == ["短答。", "细节。"]
    assert "短答。" in written[0]                                 # spoken while the rest was still streaming


def test_figures_are_checked():
    from margin.lesson import clean_figure

    assert clean_figure({"type": "compare", "rows": [{"label": "A", "items": ["S", "V", "O"], "hi": [1, 9]}]})["rows"][0]["hi"] == [1]
    assert clean_figure({"type": "flow", "items": ["only one"]}) is None
    assert clean_figure({"type": "video"}) is None
    lesson = Lesson.load(EXAMPLE)
    assert any(s.figure for s in lesson.steps)


def test_several_speakers_are_told_when_to_start():
    from margin.speaker import Clip, SpeakerHub

    bus = Bus()
    hub = SpeakerHub(bus)
    stop = threading.Event()
    hub.poll_started("ipad")
    t = threading.Thread(target=lambda: hub.play(Clip(b"mp3", "one"), stop))
    t.start()
    time.sleep(0.1)
    first = [e for e in bus.since(0, timeout=0)["events"] if e["kind"] == "speak"][-1]["data"]
    assert first["at"] is None                       # one speaker: start at once
    hub.finished(first["id"])
    t.join(1)
    hub.poll_started("phone")
    t = threading.Thread(target=lambda: hub.play(Clip(b"mp3", "two"), stop))
    t.start()
    time.sleep(0.1)
    second = [e for e in bus.since(0, timeout=0)["events"] if e["kind"] == "speak"][-1]["data"]
    assert second["at"] > time.time() * 1000         # two: a shared moment just ahead
    hub.finished(second["id"])
    t.join(1)
