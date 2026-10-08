"""Questions straight from the microphone to a realtime model.

The slow way to answer a spoken question is three waits in a row: upload the recording,
turn it into text, then ask a model. The realtime way overlaps them: while you are still
talking, the tablet streams the audio to the computer, which streams it on to an OpenAI
realtime model over one WebSocket that stays open. When you stop, the model already has
everything; it starts writing the answer at once, and the first sentence goes to the voice
while the rest is still being written.

The model writes the same JSON steps as the text model (say / focus / mark / note / figure,
then what to do next), so the e-reader is driven exactly as before. A transcript of what you
said arrives alongside, and is used to show your question and to catch the companion hearing
its own voice.

No dependencies: a minimal WebSocket client is included below.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import queue
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

# ---- a minimal WebSocket client (RFC 6455) ------------------------------------------------


class WebSocket:
    def __init__(self, url: str, headers: dict[str, str] | None = None, timeout: float = 10.0) -> None:
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "wss" else 80)
        raw = socket.create_connection((host, port), timeout=timeout)
        if parts.scheme == "wss":
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        lines = [f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed during the WebSocket handshake")
            head += chunk
        head, self._buf = head.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status + " ":
            raise ConnectionError(f"WebSocket refused: {status} {self._buf[:300]!r}")
        self.sock.settimeout(None)
        self._send_lock = threading.Lock()

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("WebSocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) if n < 4096 else _mask(payload, mask)
        with self._send_lock:
            self.sock.sendall(head + mask + masked)

    def send_json(self, obj: dict) -> None:
        self._send_frame(0x1, json.dumps(obj, ensure_ascii=False).encode())

    def recv(self) -> str:
        """The next text message (pings are answered, fragments joined)."""
        parts: list[bytes] = []
        while True:
            b1, b2 = self._read(2)
            fin, opcode, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n)
            if mask:
                data = _mask(data, mask)
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed by the server")
            if opcode == 0x9:
                self._send_frame(0xA, data)
                continue
            if opcode == 0xA:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._send_frame(0x8, b"")
        with contextlib.suppress(OSError):
            self.sock.close()


def _mask(data: bytes, mask: bytes) -> bytes:
    n = len(data)
    key = int.from_bytes((mask * (n // 4 + 1))[:n], "big")
    return (int.from_bytes(data, "big") ^ key).to_bytes(n, "big") if n else b""


# ---- one spoken question ---------------------------------------------------------------------


class LiveTurn:
    """What the realtime model makes of one stretch of speech."""

    def __init__(self, qid: str) -> None:
        self.qid = qid
        self.item_id: str | None = None
        self.response_id: str | None = None
        self.deltas: queue.Queue = queue.Queue()
        self.transcript = ""
        self.heard = threading.Event()          # transcript known (or given up on)
        self.done = threading.Event()
        self.error: str | None = None
        self.instructions = ""
        self.t_commit: float | None = None
        self.t_first_text: float | None = None
        self.on_stall: Callable[[], None] = lambda: None   # the link drops a connection that went quiet

    def pieces(self) -> Iterator[str]:
        """The answer text as the model writes it (for ``brain.StreamedAnswer``).

        A healthy realtime model starts writing within about a second. If nothing comes for a few
        seconds the connection has most likely gone stale: give up quickly (the player then asks
        again the classic way) instead of leaving the listener in silence."""
        first = True
        while True:
            wait = float(os.environ.get("MARGIN_FIRST_TEXT_TIMEOUT" if first else "MARGIN_RESPONSE_TIMEOUT",
                                        "6" if first else "20"))
            try:
                piece = self.deltas.get(timeout=wait)
            except queue.Empty:
                self.finish("Realtime answer timed out; ask again.")
                self.on_stall()
                raise RuntimeError(self.error)
            first = False
            if piece is None:
                if self.error:
                    raise RuntimeError(self.error)
                return
            yield piece

    def finish(self, error: str | None = None) -> None:
        if not self.done.is_set():
            self.error = error
            self.done.set()
            self.heard.set()
            self.deltas.put(None)


class RealtimeLink:
    """One WebSocket to the realtime model, kept open and reconnected when it drops."""

    URL = "wss://api.openai.com/v1/realtime?model={model}"

    def __init__(self, api_key: str, model: str | None = None, log: Callable[[str], None] | None = None,
                 url: str | None = None) -> None:
        self.key = api_key
        self.model = model or os.environ.get("MARGIN_REALTIME_MODEL", "gpt-realtime-2.1-mini")
        self.url = url or self.URL.format(model=self.model)
        self.log = log or (lambda _m: None)
        self.ws: WebSocket | None = None
        self.connected = threading.Event()
        self.turn: LiveTurn | None = None
        self._by_response: dict[str, LiveTurn] = {}
        self._stop = False
        self._failures = 0
        threading.Thread(target=self._run, daemon=True, name="margin-realtime").start()

    def session(self) -> dict:
        language = os.environ.get("MARGIN_LISTEN_LANGUAGE", "")
        transcription = {"model": os.environ.get("MARGIN_STT_MODEL", "gpt-4o-mini-transcribe")}
        if language:
            transcription["language"] = language
        return {"type": "realtime", "model": self.model, "output_modalities": ["text"],
                "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None,
                                    "transcription": transcription}}}

    # ---- connection ---------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop:
            started = time.monotonic()
            try:
                ws = WebSocket(self.url, {"Authorization": f"Bearer {self.key}"})
                ws.send_json({"type": "session.update", "session": self.session()})
                deadline = time.monotonic() + 12
                while True:
                    event = json.loads(ws.recv())
                    if event.get("type") == "session.updated":
                        break
                    if event.get("type") == "error":
                        raise ConnectionError(str(event.get("error"))[:300])
                    if time.monotonic() > deadline:
                        raise TimeoutError("no session.updated")
                self.ws = ws
                self.connected.set()
                if self._failures:
                    self.log("realtime: connected again")
                else:
                    self.log(f"realtime: connected ({self.model})")
                self._failures = 0
                while True:
                    self._handle(json.loads(ws.recv()))
            except Exception as err:
                self.connected.clear()
                self.ws = None
                if self.turn:
                    self.turn.finish(f"realtime connection lost: {err}")
                self._failures = 1 if time.monotonic() - started > 60 else self._failures + 1
                if self._failures <= 3 or self._failures % 10 == 0:
                    self.log(f"realtime: {type(err).__name__}: {str(err)[:200]}")
                time.sleep(min(30, 2 ** min(self._failures, 5)))

    def send(self, event: dict) -> bool:
        ws = self.ws
        if ws is None:
            return False
        try:
            ws.send_json(event)
            return True
        except OSError:
            return False

    # ---- one question -------------------------------------------------------------------
    def begin(self, qid: str) -> LiveTurn:
        if self.turn and not self.turn.done.is_set():
            self.cancel()
        self.turn = LiveTurn(qid)
        self.turn.on_stall = self._reconnect
        self.send({"type": "input_audio_buffer.clear"})
        return self.turn

    def _reconnect(self) -> None:
        """Close a connection that stopped answering; the reader thread opens a fresh one."""
        ws, self.ws = self.ws, None
        self.connected.clear()
        if ws is not None:
            self.log("realtime: no answer in time, reconnecting")
            with contextlib.suppress(OSError):
                ws.sock.shutdown(socket.SHUT_RDWR)   # wakes the reader thread blocked in recv()
            ws.close()

    def append(self, pcm24: bytes) -> None:
        if pcm24:
            self.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm24).decode()})

    def commit(self, turn: LiveTurn, instructions: str) -> bool:
        turn.instructions, turn.t_commit = instructions, time.monotonic()
        if not self.send({"type": "input_audio_buffer.commit"}):
            turn.finish("realtime not connected")
            return False
        return True

    def cancel(self) -> None:
        turn, self.turn = self.turn, None
        if not turn:
            return
        if turn.response_id and not turn.done.is_set():
            self.send({"type": "response.cancel", "response_id": turn.response_id})
        else:
            self.send({"type": "input_audio_buffer.clear"})
        turn.finish("cancelled")

    def _respond(self, turn: LiveTurn) -> None:
        self.send({"type": "response.create", "response": {
            "conversation": "none", "output_modalities": ["text"], "max_output_tokens": 900,
            "metadata": {"margin_turn": turn.qid}, "instructions": turn.instructions,
            "input": [{"type": "item_reference", "id": turn.item_id}]}})

    def _handle(self, event: dict) -> None:
        kind = event.get("type", "")
        turn = self.turn
        if kind == "error":
            message = str((event.get("error") or {}).get("message") or event.get("error"))[:300]
            self.log(f"realtime error: {message}")
            if turn and not turn.done.is_set() and "cancel" not in message.lower():
                turn.finish(message)
            return
        if kind == "input_audio_buffer.committed":
            if turn and turn.item_id is None:
                turn.item_id = event.get("item_id")
                self._respond(turn)
            return
        if kind.startswith("conversation.item.input_audio_transcription."):
            t = turn if turn and event.get("item_id") == turn.item_id else None
            if t is None:
                return
            if kind.endswith(".completed"):
                t.transcript = (event.get("transcript") or "").strip()
                t.heard.set()
            elif kind.endswith(".failed"):
                t.heard.set()
            return
        if kind == "response.created":
            response = event.get("response") or {}
            qid = (response.get("metadata") or {}).get("margin_turn")
            if turn and qid == turn.qid:
                turn.response_id = response.get("id")
                self._by_response[turn.response_id] = turn
            return
        response = event.get("response") or {}
        t = self._by_response.get(event.get("response_id") or response.get("id") or "")
        if t is None:
            return
        if kind in ("response.output_text.delta", "response.text.delta"):
            if t.t_first_text is None:
                t.t_first_text = time.monotonic()
            t.deltas.put(event.get("delta", ""))
        elif kind == "response.done":
            self._by_response.pop(t.response_id or "", None)
            status = response.get("status")
            t.finish(None if status == "completed" else f"response {status}")
            if t.item_id:   # keep the conversation empty: every question carries its own context
                self.send({"type": "conversation.item.delete", "item_id": t.item_id})

    def close(self) -> None:
        self._stop = True
        if self.ws:
            self.ws.close()


# ---- audio from the tablet -------------------------------------------------------------------


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    n = len(pcm)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", n) + pcm)


class LiveQuestion:
    """Hands a streamed question to the player: the answer stream plus the transcript gate."""

    def __init__(self, turn: LiveTurn, stream, is_echo: Callable[[str], bool],
                 cancel: Callable[[], None] = lambda: None,
                 fallback: Callable[[], str] | None = None) -> None:
        self.turn, self.stream, self.is_echo, self.cancel = turn, stream, is_echo, cancel
        self.fallback = fallback          # the classic speech-to-text, if realtime lets us down

    def wait_heard(self, timeout: float) -> str | None:
        """The transcript, '' if unknown in time; None when it was noise or the companion itself."""
        self.turn.heard.wait(timeout)
        text = self.turn.transcript
        if text and self.is_echo(text):
            return None
        return text


class Ears:
    """Receives the tablet's audio for one question at a time and starts the answer."""

    def __init__(self, player, link: RealtimeLink | None, transcriber, is_echo: Callable[[str], bool],
                 instructions: Callable[[], str], log: Callable[[str], None]) -> None:
        self.player, self.link, self.transcriber = player, link, transcriber
        self.is_echo, self.instructions, self.log = is_echo, instructions, log
        self.qid: str | None = None
        self.pcm = bytearray()
        self.turn: LiveTurn | None = None
        self.started = 0.0
        self.lock = threading.Lock()

    def audio(self, qid: str, pcm24: bytes) -> None:
        with self.lock:
            if qid != self.qid:
                self.qid, self.pcm, self.started = qid, bytearray(), time.monotonic()
                self.turn = self.link.begin(qid) if self.link and self.link.connected.is_set() else None
            self.pcm += pcm24
            if self.turn:
                self.link.append(pcm24)

    def cancel(self, qid: str | None = None) -> None:
        with self.lock:
            if qid and qid != self.qid:
                return
            if self.turn:
                self.link.cancel()
            self.qid, self.turn, self.pcm = None, None, bytearray()

    def end(self, qid: str) -> dict:
        """The tablet says you stopped talking: answer."""
        with self.lock:
            if qid != self.qid:
                return {"error": "unknown question"}
            turn, pcm, received = self.turn, bytes(self.pcm), time.monotonic()
            self.qid, self.turn, self.pcm = None, None, bytearray()
        if turn and self.link.commit(turn, self.instructions()):
            from .brain import StreamedAnswer

            lesson = self.player.lesson
            stream = StreamedAnswer(turn.pieces, lesson, self.player.focus)
            fallback = None
            if self.transcriber:
                def fallback(pcm=pcm):
                    return self.transcriber(pcm_to_wav(pcm), "audio/wav")
            self.player.ask_live(LiveQuestion(turn, stream, self.is_echo, self.link.cancel, fallback),
                                 since=received)
            return {"ok": True, "live": True}
        # no realtime connection: the classic way (transcribe, then ask)
        if not self.transcriber:
            self.player.cancel_listening()
            return {"error": "no speech-to-text configured"}
        try:
            text = self.transcriber(pcm_to_wav(pcm), "audio/wav").strip()
        except Exception as err:
            self.player.cancel_listening()
            return {"error": str(err)}
        self.log(f"speech to text: {time.monotonic() - received:.1f}s")
        if self.is_echo(text):
            self.log(f"ignored what the microphone heard: {text!r}")
            self.player.cancel_listening()
            return {"ignored": text}
        self.log(f"question: {text}")
        self.player.ask(text, since=received)
        return {"ok": True, "question": text}
