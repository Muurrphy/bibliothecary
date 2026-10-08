"""A tablet or phone as the companion's speaker, microphone and (optionally) mouth.

Open ``/speaker`` on a tablet: the voice then comes out of the tablet instead of the
computer, and the tablet listens all the time. Because the same device plays and
records, the browser's echo cancellation removes the companion's own voice from
the microphone, so you can simply start talking (no button) and it stops to listen.

Each spoken line becomes a *clip*: the audio, the text, and when available the
character timing the text-to-speech service returned. The tablet fetches the clip,
plays it and reports back when it has finished, which is when the player moves on.
If no tablet is connected, the computer plays the clip itself.
"""

from __future__ import annotations

import io
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

CJK = re.compile(r"[㐀-鿿]")


class NoSpeaker(RuntimeError):
    """No speaker page is there to play a line (the reading waits instead of going on unheard)."""


@dataclass
class Clip:
    audio: bytes
    text: str
    mime: str = "audio/mpeg"
    alignment: dict | None = None        # {"characters", "character_start_times_seconds", ...}
    id: str = ""
    timeline: list | None = field(default=None, repr=False)
    align: object = field(default=None, repr=False)        # a Future that gives ``alignment`` later
    ready: threading.Event = field(default_factory=threading.Event, repr=False)

    speech_windows: list | None = field(default=None, repr=False)
    alignment_status: str = "unverified"
    audio_duration: float | None = None

    def make_timeline(self, log: Callable[[str], None] = lambda _m: None) -> None:
        """Work out the mouth shapes (may wait for the alignment). Sets ``ready`` either way."""
        if self.ready.is_set():
            return
        try:
            from .alignment import reconcile, speech_windows, valid_alignment
            if self.alignment is None and self.align is not None:
                self.alignment = self.align.result(timeout=30)
            decoded = _decode(self.audio)
            if decoded:
                samples, rate = decoded
                self.audio_duration = len(samples) / rate
                self.speech_windows = speech_windows(samples, rate)
                self.alignment, self.alignment_status = reconcile(
                    self.alignment, self.speech_windows, self.audio_duration)
            elif valid_alignment(self.alignment):
                self.alignment_status = "provider_unverified_decoder_unavailable"
            else:
                self.alignment = None
                self.alignment_status = "unavailable"
            self.timeline = lip_timeline(self.text, self.alignment) or []
        except Exception as err:   # a mouth problem must never stop the voice
            log(f"lip timeline failed: {err}")
            self.timeline = []
        finally:
            self.ready.set()

    def seconds(self) -> float | None:
        if self.audio_duration is not None:
            return self.audio_duration
        a = self.alignment or {}
        ends = a.get("character_end_times_seconds") or []
        return float(ends[-1]) if ends else None


def lip_timeline(text: str, alignment: dict | None) -> list | None:
    """Mouth shapes for a clip, if the optional robot-lipsync package is installed."""
    from .alignment import valid_alignment
    if not valid_alignment(alignment):
        return None
    try:
        from robot_lipsync.phonemes import alignment_to_phonemes, spans_from_elevenlabs
        from robot_lipsync.planner import phonemes_to_articulation
    except ImportError:
        return None
    language = "zh" if CJK.search(text) else "en"
    spans = spans_from_elevenlabs(alignment, language)
    events = phonemes_to_articulation("margin", alignment_to_phonemes(spans),
        visual_lead_ms=float(os.environ.get("MARGIN_VISUAL_LEAD_MS", "0")))
    return [e.to_dict() for e in events]


def _decode(audio: bytes) -> tuple[list[int], int] | None:
    """Mono PCM16 samples and rate; WAV is native, compressed audio needs a decoder."""
    import array

    # PCM WAV needs no platform decoder (also useful for offline regression tests).
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            if source.getsampwidth() == 2 and source.getcomptype() == "NONE":
                pcm = array.array("h", source.readframes(source.getnframes()))
                if sys.byteorder != "little":
                    pcm.byteswap()
                channels = source.getnchannels()
                mono = [round(sum(pcm[i:i+channels])/channels) for i in range(0,len(pcm),channels)]
                return mono, source.getframerate()
    except (wave.Error, EOFError):
        pass
    tool = shutil.which("afconvert") or shutil.which("ffmpeg")
    if not tool:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.mp3"), os.path.join(tmp, "out.wav")
        with open(src, "wb") as f:
            f.write(audio)
        if tool.endswith("afconvert"):
            args = [tool, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", src, dst]
        else:
            args = [tool, "-loglevel", "error", "-y", "-i", src, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst]
        if subprocess.run(args, capture_output=True, timeout=30, check=False).returncode != 0:
            return None
        with wave.open(dst, "rb") as w:
            frames = w.readframes(w.getnframes())
            rate = w.getframerate()
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    return list(samples), rate


def estimate_alignment(audio: bytes, text: str) -> dict | None:
    """Rough character timing from the audio alone, for when no service gives real timing.

    Finds where the voice is (10 ms loudness frames), then spreads the syllables of the text
    evenly over that voiced time: one per Chinese character, about one per vowel group in
    other words. Pauses in the audio stay pauses, so the mouth closes between phrases."""
    decoded = _decode(audio)
    if not decoded:
        return None
    samples, rate = decoded
    hop = rate // 100
    levels = []
    for i in range(0, len(samples) - hop, hop):
        chunk = samples[i:i + hop]
        levels.append((sum(x * x for x in chunk[::4]) / max(1, len(chunk[::4]))) ** 0.5)
    if not levels:
        return None
    loud = sorted(levels)[int(len(levels) * 0.9)] or 1.0
    voiced = [lv > max(loud * 0.08, 120) for lv in levels]
    # bridge tiny gaps (stops inside words) so they do not count as pauses
    for i in range(1, len(voiced) - 1):
        if not voiced[i] and voiced[i - 1] and any(voiced[i + 1:i + 6]):
            voiced[i] = True
    runs, start = [], None                       # voiced stretches between pauses
    for i, v in enumerate(voiced + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start, i])
            start = None
    if not runs:
        return None
    weights = []
    for word in re.findall(r"[\u3400-\u9fff]|[A-Za-zÀ-ÿ']+|\d+|\s+|.", text):
        if CJK.match(word):
            weights.append((word, 1.0))
        elif word[0].isalpha():
            units = max(1, len(re.findall(r"[aeiouyàáâãäåèéêëìíîïòóôõöùúûü]+", word.lower())))
            weights.extend((ch, 0.85 * units / len(word)) for ch in word)
        elif word.isdigit():
            weights.extend((ch, 0.9) for ch in word)
        else:
            weights.extend((ch, 0.0) for ch in word)
    # phrases end at punctuation; a speaker usually pauses there
    phrases, cur = [], []
    for item in weights:
        cur.append(item)
        if item[0] in "，。！？、；：,.!?;:…" and any(w for _, w in cur):
            phrases.append(cur)
            cur = []
    if cur and (any(w for _, w in cur) or not phrases):
        phrases.append(cur)
    elif cur:
        phrases[-1].extend(cur)
    # merge the shortest pauses until there is one voiced stretch per phrase
    while len(runs) > len(phrases):
        gap = min(range(len(runs) - 1), key=lambda k: runs[k + 1][0] - runs[k][1])
        runs[gap:gap + 2] = [[runs[gap][0], runs[gap + 1][1]]]
    groups = list(zip(phrases, runs)) if len(runs) == len(phrases) else [
        (weights, [runs[0][0], runs[-1][1]])]
    chars, starts, ends = [], [], []
    for items, (a0, b0) in groups:
        frames = [i for i in range(a0, b0) if voiced[i]] or list(range(a0, b0))
        total, acc = sum(w for _, w in items) or 1.0, 0.0
        for ch, w in items:
            a = frames[min(len(frames) - 1, int(acc / total * len(frames)))]
            acc += w
            b = frames[min(len(frames) - 1, max(0, int(acc / total * len(frames)) - 1))] + 1
            chars.append(ch)
            starts.append(a / 100.0)
            ends.append(max(a, b) / 100.0)
    return {"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}


def lipsync_available() -> bool:
    try:
        import robot_lipsync  # noqa: F401
    except ImportError:
        return False
    return True


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def sounds_like(heard: str, said: str) -> float:
    """How much of what the microphone heard is just the companion's own line (0..1).

    Character bigram overlap, which works for Chinese and English alike."""
    a, b = _norm(heard), _norm(said)
    if not a or not b:
        return 0.0
    if a in b:
        return 1.0
    grams = lambda s: {s[i:i + 2] for i in range(max(1, len(s) - 1))}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga))


# Things speech-to-text models like to "hear" in silence or noise.
PHANTOMS = {_norm(s) for s in [
    "谢谢观看", "谢谢大家", "请不吝点赞订阅转发打赏支持明镜与点点栏目", "字幕由Amara.org社区提供", "嗯", "啊", "呃", "哦",
    "thank you", "thanks for watching", "thank you for watching", "you", "bye", "okay", "um", "uh",
    "字幕", "優優獨播劇場", "by", ".",
]}


def is_phantom(text: str) -> bool:
    n = _norm(text)
    return not n or n in PHANTOMS or (len(n) <= 1 and not CJK.search(n))


class SpeakerHub:
    """Hands clips to the connected speaker page and waits until each has been played."""

    def __init__(self, bus, log: Callable[[str], None] | None = None) -> None:
        self.bus = bus
        self.log = log or (lambda _m: None)
        self._clips: OrderedDict[str, Clip] = OrderedDict()
        self._done: dict[str, threading.Event] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._open_polls = 0
        self._last_seen = 0.0
        self._seen: dict[str, float] = {}           # speaker page id -> last poll
        self.sync_delay = 0.45                      # with several speakers: start together this much later
        self.recent: deque[str] = deque(maxlen=4)   # lines spoken lately, to recognise our own echo
        self.speaking: str | None = None
        self.owner: str | None = None
        self._active: dict | None = None
        self._errors: dict[str, str] = {}

    # ---- presence -------------------------------------------------------------------
    def register(self, sid: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._seen[sid] = now
            self._last_seen = now

    def poll_started(self, sid: str = "") -> None:
        with self._lock:
            self._open_polls += 1
            self._last_seen = time.monotonic()
            if sid:
                self._seen[sid] = self._last_seen

    def poll_finished(self) -> None:
        with self._lock:
            self._open_polls = max(0, self._open_polls - 1)
            self._last_seen = time.monotonic()

    def speakers(self) -> int:
        """How many speaker pages are around (each polls at least every ~20 s)."""
        with self._lock:
            now = time.monotonic()
            self._seen = {k: t for k, t in self._seen.items() if now - t < 30}
            return max(len(self._seen), 1 if self._open_polls else 0)

    def connected(self) -> bool:
        with self._lock:
            if self.owner:
                return time.monotonic() - self._seen.get(self.owner, 0) < 15
            return self._open_polls > 0 or time.monotonic() - self._last_seen < 4.0

    # ---- clips ----------------------------------------------------------------------
    def clip(self, clip_id: str) -> Clip | None:
        with self._lock:
            return self._clips.get(clip_id)

    def active(self) -> dict | None:
        with self._lock:
            return dict(self._active) if self._active else None

    def finished(self, clip_id: str, sid: str = "", error: str = "") -> None:
        with self._lock:
            if self.owner and sid != self.owner:
                return
            ev = self._done.get(clip_id)
            if ev and error:
                self._errors[clip_id] = error[:300]
        if ev:
            ev.set()

    def wait_connected(self, stop: threading.Event, grace: float) -> bool:
        """A page that is reloading or waking up comes back within seconds: give it the chance."""
        end = time.monotonic() + grace
        while not self.connected():
            if stop.is_set() or time.monotonic() > end:
                return self.connected()
            stop.wait(0.1)
        return True

    def play(self, clip: Clip, stop: threading.Event, on_start: Callable[[], None] | None = None) -> bool:
        """Play on the speaker page. False when there is none (the caller plays locally)."""
        single = os.environ.get("MARGIN_SINGLE_SPEAKER") == "1"
        if not self.connected():
            if not single:
                return False
            if not self.wait_connected(stop, float(os.environ.get("MARGIN_SPEAKER_GRACE", "12"))):
                if stop.is_set():
                    return True
                raise NoSpeaker("Open the mouth page and tap it: there is nothing to speak through.")
        if clip.timeline is None and not clip.ready.is_set():
            if lipsync_available() and (clip.alignment or clip.align is not None):
                threading.Thread(target=clip.make_timeline, args=(self.log,), daemon=True).start()
            else:
                clip.timeline = []
                clip.ready.set()
        done = threading.Event()
        with self._lock:
            clip.id = f"c{next(self._ids)}"
            self._clips[clip.id] = clip
            self._done[clip.id] = done
            while len(self._clips) > 12:
                old, _ = self._clips.popitem(last=False)
                self._done.pop(old, None)
        self.recent.append(clip.text)
        self.speaking = clip.text
        seconds = clip.seconds() or (len(clip.audio) / 16000.0)   # 128 kbit/s mp3 ≈ 16 kB/s
        # several phones/tablets at once: tell them all to start at the same moment
        at = round(time.time() * 1000 + self.sync_delay * 1000) if self.speakers() > 1 else None
        payload = dict(id=clip.id, text=clip.text, mime=clip.mime, at=at,
                       lips=not (clip.ready.is_set() and not clip.timeline), seconds=round(seconds, 2))
        with self._lock:
            self._active = payload
        self.bus.publish("speak", **payload)
        if on_start:
            on_start()
        deadline = time.monotonic() + seconds + float(os.environ.get("MARGIN_CLIP_GRACE", "8"))
        try:
            while not done.is_set():
                if stop.wait(0.04):
                    self.bus.publish("hush", id=clip.id)
                    return True
                if time.monotonic() > deadline:
                    # the line has had all its time: most likely it played and the "done" got lost
                    self.log(f"speaker did not confirm clip {clip.id}, going on")
                    self.bus.publish("hush", id=clip.id)
                    return True
                if not self.connected():
                    self.bus.publish("hush", id=clip.id)
                    grace = float(os.environ.get("MARGIN_SPEAKER_GRACE", "12"))
                    if self.wait_connected(stop, grace):
                        raise RuntimeError("the speaker page came back in the middle of a line")
                    if stop.is_set():
                        return True
                    if not single:
                        self.log("speaker went away in the middle of a line")
                        return True
                    raise NoSpeaker("The mouth page went away; tap it to go on.")
            with self._lock:
                error = self._errors.pop(clip.id, "")
            if error:
                raise RuntimeError(error)
            return True
        finally:
            self.speaking = None
            with self._lock:
                self._active = None
                self._done.pop(clip.id, None)
