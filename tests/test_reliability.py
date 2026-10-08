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


def test_missing_native_timestamps_are_not_replaced_with_guess(monkeypatch):
    monkeypatch.setenv('MARGIN_NATIVE_TIMING', '1')
    monkeypatch.delenv('MARGIN_VOICE_CACHE_DIR', raising=False)
    v = voice(monkeypatch)
    v._synthesize_uncached = lambda text: Clip(b'audio', text)
    with pytest.raises(RuntimeError, match='valid character timestamps'):
        v._synthesize('no timestamps')


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


def test_voice_error_pauses_without_skipping_and_can_retry():
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
    lesson = Lesson('test', [['test']], [Step(say='test')])
    player.load(lesson)
    player.play()
    assert wait_for(lambda: v.calls == 1 and bus.screen()['screen']['status'] == 'paused')
    assert player.index == 0
    player.play()
    assert wait_for(lambda: bus.screen()['screen']['status'] == 'done')
    assert v.calls == 2


def test_idle_realtime_stream_has_a_deadline(monkeypatch):
    monkeypatch.setenv('MARGIN_RESPONSE_TIMEOUT', '.02')
    turn = LiveTurn('silent_turn')
    with pytest.raises(RuntimeError, match='timed out'):
        list(turn.pieces())
    assert turn.done.is_set()


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
