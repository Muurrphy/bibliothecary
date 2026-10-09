"""Command line: ``margin serve``, ``margin build``, ``margin check``."""

from __future__ import annotations

import argparse
import sys
import time

from . import brain
from .bus import Bus
from .ingest import load_article
from .lesson import Lesson, Step
from .llm import OpenAICompatible
from .player import Player
from .server import App, lan_address, serve
from .speaker import SpeakerHub, lipsync_available
from .speech import auto_voice, make_voice
from .tls import ensure_certificate, local_hostname

LOG_FILE = "margin.log"


def _log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_env(path: str = ".env") -> None:
    """KEY=value lines from a .env file, without overriding the real environment."""
    import os
    from pathlib import Path

    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def cmd_serve(args) -> int:
    return run(Lesson.load(args.lesson), args)


class Room:
    """A running reading room: the server, the player and the addresses to open."""

    def __init__(self, app, player, servers, urls: dict[str, str], voice) -> None:
        self.app, self.player, self.servers, self.urls, self.voice = app, player, servers, urls, voice

    def close(self) -> None:
        for server in self.servers:
            server.shutdown()


def run(lesson: Lesson, args, *, client: OpenAICompatible | None = None, record=None,
        title: str = "Margin is ready.") -> int:
    """Serve a lesson until Ctrl-C. ``record`` keeps the session (see ``player.Recorder``)."""
    room = start(lesson, args, client=client, record=record)
    print(f"""
  {title}

    On the Kindle, type exactly (with http://):   {room.urls['kindle']}
    On the tablet (voice, microphone, mouth):    {room.urls['speaker_note']}
    One phone alone (article, voice, mouth):     {room.urls['phone']}
    On this computer (play / pause / ask):      {room.urls['remote']}

  {room.urls['summary']}
""", flush=True)
    if not args.paused:
        time.sleep(args.delay)
        room.player.play()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        room.close()
    return 0


def start(lesson: Lesson | None, args, *, client: OpenAICompatible | None = None, record=None) -> Room:
    """Start the reading room in the background, with a lesson or with none yet."""
    for issue in (lesson.problems() if lesson else []):
        _log(f"warning: {issue}")
    client = client or OpenAICompatible.from_env()
    if client is not None:
        client.warm()                     # open the connection before the first question
    if getattr(args, "voice", "auto") == "auto":
        voice, note = auto_voice(client, voice=args.voice_name)
        _log(f"voice: {note}")
    else:
        voice = make_voice(args.voice, client, voice=args.voice_name, rate=args.rate)

    def answerer(lesson, question, current, position=None, history=None, review=None):
        command = brain.quick_intent(question)          # "继续", "等一下", "再说一遍": no model needed
        if command:
            return {"steps": [], "then": command}
        planned = brain.forced_answer(lesson, question)   # a moment planned in the lesson (for filming)
        if planned:
            return {"steps": planned, "then": "continue"}
        if client is not None:            # steps are spoken while the model is still writing the rest
            return brain.answer_stream(client, lesson, question, current=current, position=position,
                                       history=history, review=review)
        if review and review.get("expect"):               # no model: say what a good answer says
            return {"steps": [Step(say=review["expect"])], "then": "continue"}
        return brain.scripted_answer(lesson, question)

    transcriber = (lambda audio, mime: client.transcribe(audio, mime=mime, filename="question." + {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/mpeg": "mp3"}.get(mime, mime.split("/")[-1]))) if client else None
    bus = Bus()
    hub = SpeakerHub(bus, _log)
    if hasattr(voice, "hub"):
        voice.hub = hub
    if hasattr(voice, "want_alignment"):
        voice.want_alignment = lipsync_available()   # timing for the mouth is only worth fetching with one
    player = Player(bus, voice, answerer, log=_log, record=record)
    player.forced = brain.forced_answer
    if lesson is not None:
        player.load(lesson)
    ip = lan_address()
    host = local_hostname()
    tls = None
    if args.https_port:
        try:
            tls = ensure_certificate(ip, host)
        except Exception as err:
            _log(f"could not make an HTTPS certificate ({err}); the tablet microphone needs HTTPS")
    app = App(bus, player, transcriber, log=_log, hub=hub, ca_file=str(tls[2]) if tls else None)
    import os

    if client is not None and os.environ.get("MARGIN_REALTIME", "1") != "0":
        # spoken questions go straight to a realtime model while you are still talking
        from .live import RealtimeLink

        app.ears.link = RealtimeLink(client.api_key, log=_log)
        app.ears.instructions = lambda: brain.live_instructions(player.lesson, player.focus, player.index,
                                                                player.history, player.review)

        def live_lookup(query, question):           # the realtime model asked to search the web
            _log(f"looking up: {query}")
            return brain.answer(client, player.lesson, question, current=player.focus, position=player.index,
                                history=player.history, review=player.review,
                                found=(query, brain.web_lookup(client, query)))

        app.ears.lookup = live_lookup
    # one port for everything: the Kindle uses http://, the tablet https:// (same port)
    servers = [serve(app, args.host, args.port, tls=tls[:2] if tls else None)]
    if tls:
        servers.append(serve(app, args.host, args.https_port, tls=tls[:2]))   # older bookmarks
        where = f"{host}.local" if host else ip
        speaker = (f"https://{where}:{args.port}/speaker    (or https://{ip}:{args.port}/speaker)\n"
                   f"      full screen, once: open https://{ip}:{args.port}/margin-ca.crt on the tablet,\n"
                   f"      install and trust the profile, then Share → Add to Home Screen")
    else:
        speaker = "(needs openssl for HTTPS)"
    scheme = "https" if tls else "http"
    urls = {
        "kindle": f"http://{ip}:{args.port}/",
        "base": f"{scheme}://{ip}:{args.port}",
        "phone": f"{scheme}://{ip}:{args.port}/phone",
        "remote": f"http://localhost:{args.port}/remote",
        "speaker_note": speaker,
        "summary": (f"Voice: {voice.name}{' / ' + voice.model if hasattr(voice, 'model') else ''}   Questions: "
                    f"{('realtime ' + app.ears.link.model) if app.ears.link else ('model + script' if client else 'script only (no API key)')}"
                    f"   Mouth: {'robot-lipsync' if lipsync_available() else 'simple (robot-lipsync not installed)'}"),
    }
    return Room(app, player, servers, urls, voice)


def cmd_build(args) -> int:
    client = OpenAICompatible()
    title, text, source = load_article(args.article)
    _log(f"writing a lesson for “{args.title or title}” ({len(text.split())} words)…")
    lesson = brain.build_lesson(client, args.title or title, text, explain_language=args.explain,
                                source=source, language=args.language or "en", bedtime=args.bedtime,
                                preview=args.preview, review=args.review)
    lesson.save(args.output)
    _log(f"{len(lesson.steps)} steps → {args.output}")
    for issue in lesson.problems():
        _log(f"warning: {issue}")
    return 0


def cmd_check(args) -> int:
    lesson = Lesson.load(args.lesson)
    issues = lesson.problems()
    print(f"{lesson.title}: {len(lesson.sentence_ids())} sentences, {len(lesson.steps)} steps, "
          f"{len(lesson.questions)} scripted questions")
    for issue in issues:
        print("  -", issue)
    return 1 if issues else 0


def add_serve_options(s: argparse.ArgumentParser) -> None:
    s.add_argument("--voice", default="auto", choices=["auto", "silent", "say", "openai", "elevenlabs"],
                   help="auto (default): ElevenLabs when a key and MARGIN_ELEVEN_VOICE are set, else silent")
    s.add_argument("--voice-name", help="Tingting (macOS say), coral (OpenAI) or an ElevenLabs voice id")
    s.add_argument("--rate", type=int, help="words per minute (say)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--https-port", type=int, default=8766, help="for the tablet page (browsers only allow the microphone over HTTPS); 0 = off")
    s.add_argument("--paused", action="store_true", help="wait for Play on the remote")
    s.add_argument("--delay", type=float, default=3.0, help="seconds before starting")


def add_build_options(b: argparse.ArgumentParser) -> None:
    b.add_argument("--title")
    b.add_argument("--explain", default="English", help="language of the explanation, e.g. 'Simplified Chinese'")
    b.add_argument("--language", help="language of the article, e.g. en or zh-CN (default: guessed)")
    b.add_argument("--bedtime", action="store_true", help="end with a good night")
    b.add_argument("--no-preview", dest="preview", action="store_false",
                   help="no background before the reading")
    b.add_argument("--review", type=int, default=3, metavar="N",
                   help="review questions after the reading (default 3, 0 = none)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="margin", description="An AI reading companion for old e-readers.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="serve a lesson to the e-reader")
    s.add_argument("lesson")
    add_serve_options(s)
    s.set_defaults(fn=cmd_serve)

    b = sub.add_parser("build", help="write a lesson for an article with a language model")
    b.add_argument("article", help="URL, .txt, .md or .html")
    b.add_argument("-o", "--output", default="lesson.json")
    add_build_options(b)
    b.set_defaults(fn=cmd_build)

    c = sub.add_parser("check", help="validate a lesson file")
    c.add_argument("lesson")
    c.set_defaults(fn=cmd_check)

    args = p.parse_args(argv)
    load_env()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
