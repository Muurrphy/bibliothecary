"""HTTP server: the e-reader page, the remote page, and a small JSON API.

    GET  /                 the e-reader page (open this on the Kindle)
    GET  /remote           the remote: play/pause and push-to-talk (open on the computer)
    GET  /speaker          a tablet as speaker, always-on microphone and mouth (open over HTTPS)
    GET  /api/clip/<id>    audio of one spoken line; /api/clip/<id>.json its mouth timeline
    POST /api/speaker/done {"id": "..."} the speaker page finished playing a clip
    POST /api/heard?q=<id> 24 kHz 16-bit mono audio while you talk; /api/heard/end?q=<id> when you stop
    GET  /api/screen       what the e-reader should show now
    GET  /api/poll?since=N events after N, held open up to 20 s
    POST /api/control      {"action": "play" | "pause" | "toggle" | "next" | "prev" | "restart"}
    POST /api/listen       someone started speaking: hush and wait
    POST /api/ask          {"text": "..."}  or an audio body (any audio/* type) to transcribe
    POST /api/reload       restart the program with the same arguments
"""

from __future__ import annotations

import contextlib
import json
import re
import os
import time
import socket
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .bus import Bus
from .player import Player
from .speaker import SpeakerHub, is_phantom, sounds_like

Transcriber = Callable[[bytes, str], str]


def lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))   # no packet is sent; this only picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _reexec() -> None:
    import os
    import sys

    os.execv(sys.executable, [sys.executable, "-m", "margin", *sys.argv[1:]])


def _static(name: str) -> bytes:
    return resources.files("margin").joinpath("static", name).read_bytes()


FACE_FILES = {"dotmatrix.js", "mouth_model.js"}
STATIC_FILES = {"/speaker.webmanifest": "application/manifest+json", "/speaker-icon-180.png": "image/png",
                "/speaker-icon-512.png": "image/png"}


def _face(name: str) -> bytes | None:
    """Mouth renderer files from the optional robot-lipsync package."""
    if name not in FACE_FILES:
        return None
    try:
        return resources.files("robot_lipsync").joinpath("renderers", name).read_bytes()
    except (ModuleNotFoundError, FileNotFoundError, OSError):
        return None


class App:
    def __init__(self, bus: Bus, player: Player, transcriber: Transcriber | None = None,
                 log: Callable[[str], None] | None = None, hub: SpeakerHub | None = None,
                 ca_file: str | None = None) -> None:
        self.bus, self.player, self.transcriber = bus, player, transcriber
        self.single_speaker = os.environ.get("MARGIN_SINGLE_SPEAKER") == "1"
        self.speaker_owner = None
        self.owner_seen = 0.0
        self.owner_lock = threading.Lock()
        self.log = log or (lambda _m: None)
        self.hub = hub or SpeakerHub(bus, self.log)
        self.ca_file = ca_file
        from .live import Ears

        # the tablet's microphone: without a realtime link, recordings are transcribed and asked
        self.ears = Ears(player, None, transcriber, self.is_echo, lambda: "", self.log)

    def is_echo(self, text: str) -> bool:
        """Did the microphone just hear the companion itself (or nothing at all)?"""
        if is_phantom(text):
            return True
        if len(re.sub(r"[\W_]+", "", text)) < 6:   # "为什么？" is a question even if the line says 为什么
            return False
        return any(sounds_like(text, said) >= 0.6 for said in list(self.hub.recent))

    def speaker_hello(self, data):
        sid = str(data.get("sid", ""))[:40]
        audible = not data.get("mute", False)
        with self.owner_lock:
            if sid and audible and (data.get("claim") or not self.speaker_owner or
                                    time.monotonic() - self.owner_seen > 15):
                self.speaker_owner = sid
            primary = sid == self.speaker_owner
            if primary:
                self.owner_seen = time.monotonic()
                self.hub.register(sid)
                if self.single_speaker:
                    self.hub.owner = sid
            return {"ok": True, "primary": primary, "owner": self.speaker_owner}

    def handler(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # quiet
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, data, code: int = 200) -> None:
                self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"))

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def do_GET(self):
                url = urlparse(self.path)
                if url.path in ("/", "/reader"):
                    return self._send(200, _static("reader.html"), "text/html; charset=utf-8")
                if url.path == "/remote":
                    return self._send(200, _static("remote.html"), "text/html; charset=utf-8")
                if url.path == "/speaker":
                    return self._send(200, _static("speaker.html"), "text/html; charset=utf-8")
                if url.path in STATIC_FILES:   # home-screen icon and manifest for the tablet page
                    return self._send(200, _static(url.path[1:]), STATIC_FILES[url.path])
                if url.path.startswith("/face/"):
                    body = _face(url.path[len("/face/"):])
                    if body is None:
                        return self._send(404, b'{"error": "no mouth installed"}')
                    return self._send(200, body, "text/javascript; charset=utf-8")
                if url.path.startswith("/api/clip/"):
                    name = url.path[len("/api/clip/"):]
                    clip = app.hub.clip(name.removesuffix(".json"))
                    if clip is None:
                        return self._send(404, b'{"error": "no such clip"}')
                    if name.endswith(".json"):
                        clip.ready.wait(min(20.0, float((parse_qs(url.query).get("wait") or ["0"])[0] or 0)))
                        return self._json({"id": clip.id, "text": clip.text, "ready": clip.ready.is_set(),
                                           "timeline": clip.timeline or []})
                    return self._send(200, clip.audio, clip.mime)
                if url.path == "/margin-ca.crt" and app.ca_file:
                    with open(app.ca_file, "rb") as f:
                        return self._send(200, f.read(), "application/x-x509-ca-cert")
                if url.path == "/api/time":     # for speaker pages to agree on "now"
                    return self._json({"t": time.time() * 1000})
                if url.path == "/api/screen":
                    data = app.bus.screen()
                    data["active_clip"] = app.hub.active()
                    if data["active_clip"]:
                        data["active_clip"]["resume"] = True
                    return self._json(data)
                if url.path == "/api/poll":
                    q = parse_qs(url.query)
                    since = int((q.get("since") or ["0"])[0] or 0)
                    wait = min(25.0, float((q.get("wait") or ["20"])[0]))
                    if (q.get("role") or [""])[0] != "speaker":
                        return self._json(app.bus.since(since, timeout=wait))
                    if app.single_speaker and (q.get("v") or [""])[0] != "3":
                        result = app.bus.since(since, timeout=wait)
                        if "events" in result:
                            result["events"] = [e for e in result["events"] if e["kind"] != "speak"]
                        return self._json(result)
                    app.hub.poll_started((q.get("sid") or [""])[0])
                    try:
                        return self._json(app.bus.since(since, timeout=wait))
                    finally:
                        app.hub.poll_finished()
                self._send(404, b'{"error": "not found"}')

            def do_POST(self):
                url = urlparse(self.path)
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
                if url.path == "/api/speaker/hello":
                    return self._json(app.speaker_hello(json.loads(self._body() or b"{}")))
                if app.single_speaker and url.path.startswith("/api/heard"):
                    sid = (parse_qs(url.query).get("sid") or [""])[0]
                    if not sid or sid != app.speaker_owner:
                        self._body()
                        return self._json({"error": "This page is display-only; use the primary mouth microphone."}, 409)
                if url.path == "/api/control":
                    action = json.loads(self._body() or b"{}").get("action", "")
                    fn = {"play": app.player.play, "pause": app.player.pause, "toggle": app.player.toggle,
                          "next": app.player.next, "prev": app.player.prev, "restart": app.player.restart,
                          "cancel": app.player.cancel_listening}.get(action)
                    if not fn:
                        return self._json({"error": f"unknown action {action!r}"}, 400)
                    fn()
                    return self._json({"ok": True})
                if url.path == "/api/reload":
                    # restart the whole program with the same arguments (picks up new code)
                    self._body()
                    self._json({"ok": True, "restarting": True})
                    threading.Timer(0.3, _reexec).start()
                    return None
                if url.path.startswith("/api/heard"):
                    qid = (parse_qs(url.query).get("q") or [""])[0]
                    body = self._body()
                    if url.path == "/api/heard":
                        app.ears.audio(qid, body)
                        return self._json({"ok": True})
                    if url.path == "/api/heard/end":
                        stopped = (parse_qs(url.query).get("t") or [""])[0]
                        if stopped:   # when you stopped talking, on the shared clock (ms)
                            with contextlib.suppress(ValueError):
                                late = time.time() - float(stopped) / 1000
                                if late > 1.5:
                                    app.log(f"your question reached the computer {late:.1f}s after you stopped "
                                            "(slow Wi-Fi to the phone or tablet)")
                        return self._json(app.ears.end(qid))
                    if url.path == "/api/heard/cancel":
                        app.ears.cancel(qid)
                        app.player.cancel_listening()
                        return self._json({"ok": True})
                if url.path == "/api/speaker/done":
                    data = json.loads(self._body() or b"{}")
                    app.hub.finished(str(data.get("id", "")), str(data.get("sid", "")), str(data.get("error", "")))
                    return self._json({"ok": True})
                if url.path == "/api/listen":
                    data = json.loads(self._body() or b"{}")
                    if app.single_speaker and data.get("sid") != app.speaker_owner:
                        return self._json({"error": "Only the primary mouth microphone listens."}, 409)
                    app.player.listening()
                    return self._json({"ok": True})
                if url.path == "/api/ask":
                    received = time.monotonic()
                    body = self._body()
                    if ctype.startswith("audio/") or ctype == "application/octet-stream":
                        if not app.transcriber:
                            app.player.cancel_listening()
                            return self._json({"error": "no speech-to-text configured (set OPENAI_API_KEY)"}, 400)
                        try:
                            text = app.transcriber(body, ctype).strip()
                            app.log(f"speech to text: {time.monotonic() - received:.1f}s")
                        except Exception as err:
                            app.player.cancel_listening()
                            return self._json({"error": str(err)}, 502)
                        if app.is_echo(text):
                            # a cough, the room, or the companion hearing itself: carry on
                            app.log(f"ignored what the microphone heard: {text!r}")
                            app.player.cancel_listening()
                            return self._json({"ignored": text})
                    else:
                        text = json.loads(body or b"{}").get("text", "")
                    text = text.strip()
                    if not text:
                        app.player.cancel_listening()
                        return self._json({"error": "empty question"}, 400)
                    app.log(f"question: {text}")
                    app.player.ask(text, since=received)
                    return self._json({"ok": True, "question": text})
                self._send(404, b'{"error": "not found"}')

        return Handler


class _Server(ThreadingHTTPServer):
    """HTTP and HTTPS on the same port.

    The e-reader speaks plain HTTP; the tablet needs HTTPS for its microphone; and some
    browsers quietly switch a typed http:// address to https://. So each connection is
    looked at first: a TLS handshake starts with byte 0x16, anything else is plain HTTP."""

    daemon_threads = True
    tls_context = None

    def finish_request(self, request, client_address):
        wrapped = None
        if self.tls_context is not None:
            import ssl

            try:
                request.settimeout(15)
                if request.recv(1, socket.MSG_PEEK) == b"\x16":
                    request = wrapped = self.tls_context.wrap_socket(request, server_side=True)
                request.settimeout(None)
            except (OSError, ssl.SSLError):
                return
        try:
            self.RequestHandlerClass(request, client_address, self)
        finally:
            if wrapped is not None:
                try:
                    wrapped.close()
                except OSError:
                    pass


def serve(app: App, host: str = "0.0.0.0", port: int = 8765,
          tls: tuple[str, str] | None = None) -> ThreadingHTTPServer:
    """Serve ``app``. With ``tls=(certificate chain, key)`` the port also speaks HTTPS."""
    server = _Server((host, port), app.handler())
    if tls:
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(tls[0]), str(tls[1]))
        server.tls_context = ctx
    threading.Thread(target=server.serve_forever, daemon=True, name="margin-http").start()
    return server
