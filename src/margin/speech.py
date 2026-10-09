"""Voices (text to speech) and ears (speech to text).

Every voice blocks until it has finished speaking and can be cut off with a
``threading.Event`` - that is how a question interrupts the explanation.
The silent voice speaks nothing and just waits about as long as reading the
caption takes, so the whole thing also works with the sound off.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout  # not the builtin one before 3.11

from . import net
from .llm import OpenAICompatible
from .speaker import Clip


class Recorder:
    """Keeps a copy of every line as it is played, for editing a video afterwards.

    With ``MARGIN_RECORD_DIR`` set, each spoken line is saved there as an mp3 named by the
    moment it started, and ``timeline.jsonl`` notes when it started and stopped (stopped
    early means it was interrupted). ``margin-stitch`` (python -m margin.stitch) joins them
    into one track on the real timeline."""

    def __init__(self, folder: str | None = None) -> None:
        self._folder = folder                # None: read MARGIN_RECORD_DIR when a line plays (after .env)
        self._lock = threading.Lock()
        self._n = 0

    @property
    def folder(self) -> Path | None:
        folder = self._folder if self._folder is not None else os.environ.get("MARGIN_RECORD_DIR", "")
        return Path(folder).expanduser() if folder else None

    def play(self, audio: bytes, text: str, play, stop: threading.Event | None = None) -> object:
        """Run ``play()`` (which sounds the line) and keep the line with its start and end."""
        folder = self.folder
        if folder is None:
            return play()
        start = time.time()
        with self._lock:
            self._n += 1
            n = self._n
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(start)) + f".{int(start % 1 * 1000):03d}_{n:04d}.mp3"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(audio)
        except OSError as err:
            _warn(f"could not keep a recording of the line: {err}")
            return play()
        try:
            return play()
        finally:
            line = {"file": name, "start": round(start, 3), "end": round(time.time(), 3), "text": text,
                    "cut": bool(stop is not None and stop.is_set())}     # interrupted: stopped at "end"
            with self._lock, open(folder / "timeline.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")


RECORDER = Recorder()


def _warn(msg: str) -> None:
    line = time.strftime("%H:%M:%S") + " " + msg
    print(line, flush=True)
    try:
        with open("margin.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def reading_seconds(text: str) -> float:
    cjk = len(re.findall(r"[㐀-鿿]", text))
    words = len(re.findall(r"[A-Za-zÀ-ÿ0-9]+", text))
    return max(1.2, cjk / 4.2 + words / 2.6 + 0.4)


class SilentVoice:
    name = "silent"

    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed

    def speak(self, text: str, stop: threading.Event) -> None:
        stop.wait(reading_seconds(text) / self.speed)


class _ProcessVoice:
    """Runs a player process and kills it when interrupted."""

    def _run(self, args: list[str], stop: threading.Event) -> None:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while proc.poll() is None:
            if stop.wait(0.05):
                proc.terminate()
                break


class SayVoice(_ProcessVoice):
    """macOS ``say``. ``margin voices`` lists e.g. Tingting (zh-CN) or Samantha (en-US)."""

    name = "say"

    def __init__(self, voice: str | None = None, rate: int | None = None) -> None:
        if not shutil.which("say"):
            raise RuntimeError("the 'say' voice needs macOS")
        self.voice, self.rate = voice, rate

    def speak(self, text: str, stop: threading.Event) -> None:
        args = ["say"]
        if self.voice:
            args += ["-v", self.voice]
        if self.rate:
            args += ["-r", str(self.rate)]
        self._run(args + [text], stop)


def _player() -> list[str]:
    for args in (["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["mpg123", "-q"]):
        if shutil.which(args[0]):
            return args
    raise RuntimeError("no audio player found (afplay, ffplay or mpg123)")


class OpenAIVoice(_ProcessVoice):
    name = "openai"

    def __init__(self, client: OpenAICompatible, voice: str = "coral", model: str | None = None,
                 instructions: str | None = None) -> None:
        self.hub = None
        self.on_start = None
        self.client, self.voice = client, voice
        self.model = model or os.environ.get("MARGIN_TTS_MODEL", "gpt-4o-mini-tts")
        self.instructions = instructions or "Speak warmly and calmly, like reading to a friend late at night."
        self.player = _player()

    def speak(self, text: str, stop: threading.Event) -> None:
        if stop.is_set() or not text.strip():
            return
        audio = self.client.speech(text, voice=self.voice, model=self.model, instructions=self.instructions)
        if self.hub and RECORDER.play(audio, text, lambda: self.hub.play(Clip(audio, text), stop, on_start=self.on_start), stop):
            return
        if self.on_start:
            self.on_start()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            self._run(self.player + [path], stop)
        finally:
            os.unlink(path)


def _keychain(service: str, prefix: str = "") -> str | None:
    """A secret from the macOS Keychain. The item stored under the login account
    wins; with ``prefix`` (e.g. "sk_"), values that do not look like a key are skipped
    (a Keychain can also hold a key *id* under the same service name)."""
    if not shutil.which("security"):
        return None
    found = []
    for account in (os.environ.get("USER") or "", ""):
        args = ["security", "find-generic-password", "-s", service, "-w"]
        if account:
            args[2:2] = ["-a", account]
        out = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
        value = out.stdout.strip()
        if value:
            if value.startswith(prefix):
                return value
            found.append(value)
    return found[0] if found and not prefix else None


class ElevenLabsVoice(_ProcessVoice):
    """ElevenLabs text to speech, with the next lines synthesized ahead of time.

    The key comes from ``ELEVENLABS_API_KEY`` or, on macOS, from the Keychain item
    named by ``MARGIN_ELEVENLABS_KEYCHAIN``. ``MARGIN_ELEVEN_MODEL`` picks the model;
    by default the newest v4 model the account offers is used."""

    name = "elevenlabs"
    API = "https://api.elevenlabs.io/v1"
    PREFERENCE = ("eleven_v4", "v4", "eleven_v3", "eleven_multilingual_v2")

    def __init__(self, voice_id: str, model: str | None = None, settings: dict | None = None) -> None:
        if not voice_id:
            raise RuntimeError("the elevenlabs voice needs --voice-name <voice id>")
        env = os.environ.get("ELEVENLABS_API_KEY", "")
        self.key = (env if env.startswith("sk_") else "") or _keychain(
            os.environ.get("MARGIN_ELEVENLABS_KEYCHAIN", "Margin ElevenLabs API Key"), prefix="sk_") or env
        if not self.key:
            raise RuntimeError("no ElevenLabs key found: set ELEVENLABS_API_KEY (starts with sk_) or store it in the Keychain")
        self.voice_id = voice_id
        self._fallbacks: list[str] = []
        configured = os.environ.get("MARGIN_ELEVEN_SETTINGS")
        if settings is not None:
            self.settings = dict(settings)
        elif configured is not None:
            self.settings = json.loads(configured)
            if not isinstance(self.settings, dict):
                raise ValueError("MARGIN_ELEVEN_SETTINGS must be a JSON object")
        else:
            self.settings = {"stability": 0.6, "similarity_boost": 0.9, "style": 0.1,
                             "use_speaker_boost": True, "speed": 0.97}
        self.strict_settings = os.environ.get("MARGIN_ELEVEN_STRICT_SETTINGS") == "1"
        self.model = model or os.environ.get("MARGIN_ELEVEN_MODEL") or self._pick_model()
        self.player = _player()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="margin-tts")
        # answers get their own workers: they never queue behind lines prepared for later
        self._urgent_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="margin-tts-answer")
        self.log = _warn
        self._cache: dict[str, Future] = {}
        self._lock = threading.Lock()
        self.timestamps = True
        self.hub = None             # a SpeakerHub: play on the tablet when one is connected
        self.want_alignment = False  # character timing for a mouth (set when a mouth is installed)
        self.on_start = None         # called when a line starts sounding (for timing)
        self.aligner = os.environ.get("MARGIN_ALIGN", "elevenlabs")   # or "local": estimate from the audio
        self._align_failures = 0
        self._align_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="margin-align")

    def _request(self, method: str, path: str, body: dict | None = None) -> bytes:
        return net.request(method, self.API + path, json.dumps(body).encode() if body else None, timeout=60,
                           headers={"xi-api-key": self.key, "Content-Type": "application/json"}).read()

    def _pick_model(self) -> str:
        try:
            models = json.loads(self._request("GET", "/models"))
            ids = [m["model_id"] for m in models if m.get("can_do_text_to_speech", True)]
        except Exception:
            # the key may not be allowed to list models: try v4 first, fall back when refused
            self._fallbacks = ["eleven_v4_turbo", "eleven_v3", "eleven_multilingual_v2"]
            return "eleven_v4"
        for want in self.PREFERENCE:
            plain = [i for i in ids if want in i and "turbo" not in i and "flash" not in i]
            if plain:
                return min(plain)
            fast = [i for i in ids if want in i]
            if fast:
                return min(fast)
        return ids[0] if ids else "eleven_multilingual_v2"

    def _post(self, text: str, suffix: str = "") -> bytes:
        path = f"/text-to-speech/{self.voice_id}{suffix}?output_format=mp3_44100_128"
        while True:
            body = {"text": text, "model_id": self.model, "voice_settings": self.settings}
            try:
                return self._request("POST", path, body)
            except urllib.error.HTTPError as err:
                detail = err.read().decode("utf-8", "replace").lower()
                if err.code in (400, 404, 422) and "model" in detail and self._fallbacks:
                    _warn(f"model {self.model} unavailable ({err.code}), trying {self._fallbacks[0]}")
                    self.model = self._fallbacks.pop(0)
                    continue
                if err.code != 400:
                    raise RuntimeError(f"ElevenLabs {err.code}: {detail[:300]}") from err
                if self.strict_settings:
                    raise RuntimeError(f"ElevenLabs 400: selected voice settings rejected: {detail[:300]}") from err
                _warn(f"ElevenLabs 400 with full settings, retrying with basic ones: {detail[:300]}")
                break
        # some models accept fewer settings; fall back to the core ones, and keep using those
        core = {k: self.settings[k] for k in ("stability", "similarity_boost") if k in self.settings}
        audio = self._request("POST", path, {"text": text, "model_id": self.model, "voice_settings": core})
        self.settings = core
        return audio

    def _synthesize(self, text: str) -> Clip:
        native = os.environ.get("MARGIN_NATIVE_TIMING") == "1"
        cache = os.environ.get("MARGIN_VOICE_CACHE_DIR")
        path = None
        if cache:
            signature = json.dumps([self.voice_id, self.model, self.settings, text], ensure_ascii=False)
            path = Path(cache) / (hashlib.sha256(signature.encode()).hexdigest() + ".json")
            if path.exists():
                data = json.loads(path.read_text())
                clip = Clip(base64.b64decode(data["audio"]), text, alignment=data.get("alignment"))
                if not native or self._valid_alignment(clip.alignment):
                    if native:
                        clip.make_timeline(_warn)
                    return clip
        clip = self._synthesize_uncached(text)
        if native and not self._valid_alignment(clip.alignment) and self.timestamps:
            clip = self._synthesize_uncached(text)          # one more try for real character timing
        if native:
            if not self._valid_alignment(clip.alignment):
                # Never go silent over the mouth: speak the line, and let the mouth use an estimate
                # (or follow loudness). A missing timestamp costs a little lip accuracy, not a line.
                _warn(f"no character timestamps for {text[:24]!r}; the mouth uses an estimate for this line")
                if clip.align is None and self.want_alignment:
                    clip.align = self._align_pool.submit(self._align, clip.audio, text)
            clip.make_timeline(_warn)
        if path and self._valid_alignment(clip.alignment):
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_suffix(".tmp")
            pending.write_text(json.dumps({"text": text, "audio": base64.b64encode(clip.audio).decode(),
                                           "alignment": clip.alignment}, ensure_ascii=False))
            pending.replace(path)
        return clip

    @staticmethod
    def _valid_alignment(alignment) -> bool:
        from .alignment import valid_alignment
        return valid_alignment(alignment)

    def _synthesize_uncached(self, text: str) -> Clip:
        """Audio plus, when the model offers it, when each character is spoken (for a mouth)."""
        if self.timestamps:
            try:
                data = json.loads(self._post(text, "/with-timestamps"))
                alignment = data.get("alignment") or data.get("normalized_alignment")
                return Clip(base64.b64decode(data["audio_base64"]), text, alignment=alignment)
            except (RuntimeError, urllib.error.HTTPError, ValueError, KeyError) as err:
                if isinstance(err, RuntimeError) and not re.match(r"ElevenLabs (400|404|405|422)", str(err)):
                    raise
                if isinstance(err, urllib.error.HTTPError) and err.code not in (400, 404, 405, 422):
                    raise
                _warn(f"no timestamps from this ElevenLabs model ({err}); aligning the audio instead")
                self.timestamps = False
        clip = Clip(self._post(text), text)
        if self.want_alignment:
            clip.align = self._align_pool.submit(self._align, clip.audio, text)
        return clip

    def _align(self, audio: bytes, text: str) -> dict | None:
        """Character timing for a clip: ElevenLabs forced alignment, else an estimate from the audio."""
        if self.aligner == "elevenlabs":
            try:
                return self._forced_alignment(audio, text)
            except Exception as err:
                self._align_failures += 1
                _warn(f"forced alignment failed ({err}); estimating mouth timing from the audio")
                if self._align_failures >= 2:
                    self.aligner = "local"
        from .speaker import estimate_alignment
        return estimate_alignment(audio, text)

    def _forced_alignment(self, audio: bytes, text: str) -> dict:
        boundary = "margin" + os.urandom(8).hex()
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n'.encode() + text.encode() + b"\r\n",
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="line.mp3"\r\n'
            "Content-Type: audio/mpeg\r\n\r\n".encode() + audio + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        data = json.loads(net.request("POST", self.API + "/forced-alignment", b"".join(parts), timeout=30, headers={
            "xi-api-key": self.key, "Content-Type": f"multipart/form-data; boundary={boundary}"}).read())
        chars = data.get("characters") or []
        if not chars:
            raise RuntimeError("no characters in the alignment")
        return {"characters": [c.get("text", "") for c in chars],
                "character_start_times_seconds": [float(c.get("start", 0)) for c in chars],
                "character_end_times_seconds": [float(c.get("end", 0)) for c in chars]}

    def prepare(self, text: str, urgent: bool = False) -> None:
        with self._lock:
            if text not in self._cache:
                if len(self._cache) > 64:
                    self._cache.clear()
                if urgent:
                    self._cache[text] = self._urgent_pool.submit(self._timed, text)
                else:
                    self._cache[text] = self._pool.submit(self._synthesize, text)

    def _timed(self, text: str) -> Clip:
        t0 = time.monotonic()
        clip = self._synthesize(text)
        self.log(f"voice for an answer line: {time.monotonic() - t0:.1f}s ({len(text)} characters)")
        return clip

    def speak(self, text: str, stop: threading.Event) -> None:
        if stop.is_set() or not text.strip():
            return
        self.prepare(text)
        with self._lock:
            future = self._cache[text]
        try:
            deadline = time.monotonic() + 30
            while True:
                if stop.is_set():
                    return
                try:
                    clip = future.result(timeout=0.1)
                    break
                except (TimeoutError, FutureTimeout):
                    if future.done():
                        raise
                    if time.monotonic() > deadline:
                        raise RuntimeError("Voice preparation timed out; retry playback.")
        except Exception as err:
            with self._lock:
                if self._cache.get(text) is future:
                    self._cache.pop(text, None)
            raise RuntimeError(f"Voice unavailable: {err}") from err
        if stop.is_set():
            return
        if self.hub and RECORDER.play(clip.audio, text, lambda: self.hub.play(clip, stop, on_start=self.on_start), stop):
            return
        if self.on_start:
            self.on_start()
        audio = clip.audio
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            self._run(self.player + [path], stop)
        finally:
            os.unlink(path)


def _eleven_voice_id() -> str:
    return os.environ.get("MARGIN_ELEVEN_VOICE") or os.environ.get("ELEVENLABS_VOICE_ID") or ""


def auto_voice(client: OpenAICompatible | None = None, **options) -> tuple[object, str]:
    """The voice to use when none was asked for, and a line saying which and why.

    An ElevenLabs voice when one is set up: it is the one that plays on the phone with the mouth
    moving. Otherwise silence, said plainly, so a reader who hears nothing knows what to add."""
    voice_id = options.get("voice") or _eleven_voice_id()
    if voice_id:
        try:
            return ElevenLabsVoice(voice_id), f"ElevenLabs voice {voice_id}"
        except Exception as err:                         # no key, no network: read on, without sound
            return SilentVoice(options.get("speed", 1.0)), f"SILENT, the ElevenLabs voice did not start: {err}"
    return SilentVoice(options.get("speed", 1.0)), ("SILENT: no voice is set up, so the phone stays quiet and "
                                                    "the mouth still. Add an ElevenLabs key and MARGIN_ELEVEN_VOICE "
                                                    "(see docs/configuration.md)")


def make_voice(kind: str, client: OpenAICompatible | None = None, **options) -> object:
    if kind == "silent":
        return SilentVoice(options.get("speed", 1.0))
    if kind == "say":
        return SayVoice(options.get("voice"), options.get("rate"))
    if kind == "elevenlabs":
        return ElevenLabsVoice(options.get("voice") or _eleven_voice_id())
    if kind == "openai":
        if client is None:
            raise RuntimeError("the openai voice needs an API key (OPENAI_API_KEY)")
        return OpenAIVoice(client, voice=options.get("voice") or "coral")
    raise ValueError(f"unknown voice {kind!r}")


class Stopwatch:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)
