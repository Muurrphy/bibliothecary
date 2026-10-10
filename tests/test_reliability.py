import threading
import time
from concurrent.futures import Future

import pytest

from margin.bus import Bus
from margin.lesson import Lesson, Step
from margin.live import LiveTurn
from margin.player import Player
from margin.server import App
from margin.speaker import Clip, SpeakerHub
from margin.speech import ElevenLabsVoice


def wait_for(fn, timeout=2):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if fn():
            return True
        time.sleep(.01)
    return False


def voice(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'sk_test')
    # These tests never play local audio; do not depend on an OS audio player.
    monkeypatch.setattr('margin.speech._player', lambda: ['unused-test-player'])
    return ElevenLabsVoice('test_voice', model='eleven_v4')


def test_replay_reuses_completed_audio(monkeypatch):
    v = voice(monkeypatch)
    generated = []
    v._synthesize = lambda text: (generated.append(text) or Clip(b'audio', text))
    class Hub:
        def play(self, *args, **kwargs):
            return True
    v.hub = Hub()
    v.speak('same sentence', threading.Event())
    v.speak('same sentence', threading.Event())
    assert generated == ['same sentence']


def test_stop_interrupts_pending_synthesis(monkeypatch):
    v = voice(monkeypatch)
    v._cache['pending'] = Future()
    stop = threading.Event()
    worker = threading.Thread(target=v.speak, args=('pending', stop))
    worker.start()
    stop.set()
    worker.join(.5)
    assert not worker.is_alive()


def test_missing_native_timestamps_never_silence_a_line(monkeypatch):
    monkeypatch.setenv('MARGIN_NATIVE_TIMING', '1')
    monkeypatch.delenv('MARGIN_VOICE_CACHE_DIR', raising=False)
    v = voice(monkeypatch)
    tries = []
    v._synthesize_uncached = lambda text: (tries.append(text) or Clip(b'audio', text))
    clip = v._synthesize('no timestamps')
    assert clip.audio == b'audio' and clip.ready.is_set()
    assert tries == ['no timestamps', 'no timestamps']      # one more try for real timing first


def test_only_primary_completion_advances_audio():
    bus, hub = Bus(), None
    hub = SpeakerHub(bus)
    hub.owner = 'phone'
    hub.poll_started('phone')
    errors = []
    def run():
        try:
            hub.play(Clip(b'audio', 'test'), threading.Event())
        except Exception as e:
            errors.append(e)
    worker = threading.Thread(target=run)
    worker.start()
    assert wait_for(lambda: hub.active())
    clip = hub.active()['id']
    hub.finished(clip, 'tablet')
    worker.join(.1)
    assert worker.is_alive()
    hub.finished(clip, 'phone')
    worker.join(1)
    assert not worker.is_alive() and not errors


def test_device_decode_error_is_propagated():
    hub = SpeakerHub(Bus())
    hub.owner = 'phone'
    hub.poll_started('phone')
    errors = []
    def run():
        try:
            hub.play(Clip(b'audio', 'test'), threading.Event())
        except Exception as e:
            errors.append(str(e))
    worker = threading.Thread(target=run)
    worker.start()
    assert wait_for(lambda: hub.active())
    hub.finished(hub.active()['id'], 'phone', 'decode failed')
    worker.join(1)
    assert errors == ['decode failed']
    assert hub.active() is None


def test_a_voice_hiccup_is_retried_and_the_reading_goes_on():
    class RecoveringVoice:
        def __init__(self):
            self.calls = 0
        def speak(self, text, stop):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('temporary voice error')
    v = RecoveringVoice()
    bus = Bus()
    player = Player(bus, v)
    player.load(Lesson('test', [['test']], [Step(say='one'), Step(say='two')]))
    player.play()
    assert wait_for(lambda: bus.screen()['screen']['status'] == 'done')
    assert v.calls == 3


def test_a_line_that_keeps_failing_is_skipped_not_a_full_stop():
    said = []
    class Voice:
        def speak(self, text, stop):
            if text == 'broken':
                raise RuntimeError('bad line')
            said.append(text)
    bus = Bus()
    player = Player(bus, Voice())
    player.load(Lesson('test', [['test']], [Step(say='broken'), Step(say='fine')]))
    player.play()
    assert wait_for(lambda: bus.screen()['screen']['status'] == 'done')
    assert said == ['fine']


def test_no_speaker_page_pauses_without_skipping():
    from margin.speaker import NoSpeaker

    class Voice:
        calls = 0
        def speak(self, text, stop):
            Voice.calls += 1
            if Voice.calls == 1:
                raise NoSpeaker('no page')
    bus = Bus()
    player = Player(bus, Voice())
    player.load(Lesson('test', [['test']], [Step(say='only line')]))
    player.play()
    assert wait_for(lambda: Voice.calls == 1 and bus.screen()['screen']['status'] == 'paused')
    assert player.index == 0
    player.play()
    assert wait_for(lambda: bus.screen()['screen']['status'] == 'done')
    assert Voice.calls == 2


def test_an_unconfirmed_clip_does_not_stop_the_reading(monkeypatch):
    hub = SpeakerHub(Bus())
    hub.owner = 'phone'
    hub.register('phone')
    monkeypatch.setenv('MARGIN_CLIP_GRACE', '.2')
    clip = Clip(b'x' * 160, 'short')            # about 0.01 s of audio, never confirmed by the page
    assert hub.play(clip, threading.Event()) is True


def test_speaker_page_that_reloads_is_waited_for(monkeypatch):
    monkeypatch.setenv('MARGIN_SINGLE_SPEAKER', '1')
    monkeypatch.setenv('MARGIN_SPEAKER_GRACE', '2')
    hub = SpeakerHub(Bus())
    hub.owner = 'phone'
    threading.Timer(.3, lambda: hub.register('phone')).start()
    stop = threading.Event()
    result = []
    worker = threading.Thread(target=lambda: result.append(hub.play(Clip(b'a', 'line'), stop)))
    worker.start()
    assert wait_for(lambda: hub.active(), timeout=3)
    hub.finished(hub.active()['id'], 'phone')
    worker.join(2)
    assert result == [True]


def test_no_speaker_at_all_raises_no_speaker(monkeypatch):
    from margin.speaker import NoSpeaker

    monkeypatch.setenv('MARGIN_SINGLE_SPEAKER', '1')
    monkeypatch.setenv('MARGIN_SPEAKER_GRACE', '.1')
    hub = SpeakerHub(Bus())
    with pytest.raises(NoSpeaker):
        hub.play(Clip(b'a', 'line'), threading.Event())


def test_idle_realtime_stream_has_a_deadline(monkeypatch):
    monkeypatch.setenv('MARGIN_FIRST_TEXT_TIMEOUT', '.02')
    turn = LiveTurn('silent_turn')
    stalled = []
    turn.on_stall = lambda: stalled.append(True)
    with pytest.raises(RuntimeError, match='timed out'):
        list(turn.pieces())
    assert turn.done.is_set() and stalled == [True]


def test_muted_tablet_never_takes_primary_microphone():
    class Voice:
        def speak(self, *args):
            pass
    bus = Bus()
    app = App(bus, Player(bus, Voice()))
    assert app.speaker_hello({'sid':'phone', 'claim':True})['primary']
    assert not app.speaker_hello({'sid':'ipad', 'mute':True})['primary']
    assert app.speaker_owner == 'phone'


def test_ready_audio_can_play_before_first_long_poll(monkeypatch):
    monkeypatch.setenv('MARGIN_SINGLE_SPEAKER', '1')
    class Voice:
        def speak(self, *args):
            pass
    bus = Bus()
    app = App(bus, Player(bus, Voice()))
    app.speaker_hello({'sid':'phone', 'claim':True})
    assert app.hub.owner == 'phone'
    assert app.hub.connected()
    assert app.hub._open_polls == 0


def test_selected_voice_settings_cannot_silently_fall_back(monkeypatch):
    import io
    import json
    import urllib.error

    selected = {'stability': 1.0, 'similarity_boost': 1.0, 'style': 0.0,
                'use_speaker_boost': True, 'speed': 1.14}
    monkeypatch.setenv('MARGIN_ELEVEN_SETTINGS', json.dumps(selected))
    monkeypatch.setenv('MARGIN_ELEVEN_STRICT_SETTINGS', '1')
    v = voice(monkeypatch)
    requests = []
    def refused(method, path, body=None):
        requests.append(body)
        raise urllib.error.HTTPError(path, 400, 'bad settings', {},
            io.BytesIO(b'{"detail":"invalid voice settings"}'))
    v._request = refused
    with pytest.raises(RuntimeError, match='selected voice settings rejected'):
        v._post('test')
    assert len(requests) == 1
    assert requests[0]['voice_settings'] == selected
    assert v.settings == selected


def test_the_voice_is_chosen_for_you_and_silence_is_said_out_loud(monkeypatch):
    from margin import speech

    monkeypatch.delenv("MARGIN_ELEVEN_VOICE", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    voice, note = speech.auto_voice(None)
    assert voice.name == "silent" and "SILENT" in note and "MARGIN_ELEVEN_VOICE" in note

    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v123")
    monkeypatch.setattr(speech, "ElevenLabsVoice", lambda voice_id: type("V", (), {"name": "elevenlabs", "id": voice_id})())
    voice, note = speech.auto_voice(None)
    assert voice.name == "elevenlabs" and voice.id == "v123" and "v123" in note

    def broken(voice_id):
        raise RuntimeError("no ElevenLabs key found")
    monkeypatch.setattr(speech, "ElevenLabsVoice", broken)
    voice, note = speech.auto_voice(None)
    assert voice.name == "silent" and "no ElevenLabs key found" in note


def test_serving_defaults_to_the_automatic_voice():
    import argparse
    from margin import cli

    p = argparse.ArgumentParser()
    cli.add_serve_options(p)
    assert p.parse_args([]).voice == "auto"


def test_played_lines_can_be_kept_for_editing(tmp_path):
    import json
    from margin import speech

    rec = speech.Recorder(str(tmp_path / "rec"))
    played = []
    assert rec.play(b"ID3fake", "你好", lambda: played.append(1) or True) is True
    files = [p.name for p in (tmp_path / "rec").glob("*.mp3")]
    timeline = [json.loads(x) for x in (tmp_path / "rec" / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
    assert played == [1] and len(files) == 1 and timeline[0]["file"] == files[0] and timeline[0]["text"] == "你好"
    assert timeline[0]["end"] >= timeline[0]["start"]
    off = speech.Recorder("")
    assert off.play(b"x", "y", lambda: "sounded") == "sounded" and off.folder is None


def test_the_recording_folder_is_read_when_a_line_plays(tmp_path, monkeypatch):
    from margin import speech

    monkeypatch.delenv("MARGIN_RECORD_DIR", raising=False)
    rec = speech.Recorder()                       # made at import, before .env is read
    monkeypatch.setenv("MARGIN_RECORD_DIR", str(tmp_path / "later"))
    rec.play(b"ID3", "hi", lambda: True)
    assert (tmp_path / "later" / "timeline.jsonl").is_file()
