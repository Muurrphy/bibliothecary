"""Command line: ``bibliothecary`` (or ``biblio``) prepare / read / report / records."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from margin import cli as margin_cli
from margin.lesson import Lesson
from margin.llm import OpenAICompatible

from . import __version__, library, report
from .prepare import prepare
from .records import Ledger

_log = margin_cli._log


def _folder(where: str | None, *, fallback) -> Path:
    """A reading folder from a path (folder or lesson file inside one), or the default."""
    if not where:
        folder = fallback()
        if folder is None:
            raise SystemExit(f"no readings yet in {library.readings_dir()}; start with: biblio prepare <article>")
        return folder
    path = Path(where).expanduser()
    if path.is_dir() and (path / "lesson.json").is_file():
        return path
    if path.is_file() and path.name == "lesson.json":
        return path.parent
    named = library.readings_dir() / where
    if (named / "lesson.json").is_file():
        return named
    raise SystemExit(f"not a reading: {where}")


def cmd_prepare(args) -> int:
    folder = prepare(OpenAICompatible(), args.article, title=args.title, explain=args.explain,
                     language=args.language, bedtime=args.bedtime, preview=args.preview, review=args.review,
                     log=_log)
    lesson = Lesson.load(folder / "lesson.json")
    path = folder / "report.md"
    parts = {p: sum(1 for s in lesson.steps if s.part == p) for p in ("preview", "review")}
    print(f"\n  Ready for tonight: {folder}\n"
          f"    {parts['preview']} background steps, {len(lesson.steps) - parts['preview'] - parts['review']} reading steps,"
          f" {sum(1 for s in lesson.steps if s.expect)} review questions\n"
          f"    reading guide: {path}\n\n  Read it with: biblio read\n")
    return 0


def cmd_read(args) -> int:
    where = Path(args.reading).expanduser() if args.reading else None
    if where and where.is_file() and where.name != "lesson.json":
        lesson = Lesson.load(where)               # a lesson from elsewhere (e.g. examples/): file it first
        folder = library.new_reading(lesson)
        _log(f"filed {where.name} as {folder.name}")
    else:
        folder = _folder(args.reading, fallback=library.next_unread)
        lesson = Lesson.load(folder / "lesson.json")
    if not (folder / "report.md").exists():
        report.write(folder)
    client = OpenAICompatible.from_env()
    ledger = Ledger(folder, lesson, client=client, log=_log)
    try:
        return margin_cli.run(lesson, args, client=client, record=ledger.record,
                              title=f"Bibliothecary is ready: “{lesson.title}”\n  Records: {folder}")
    finally:
        _log("filing tonight's reading report…")
        ledger.close()


def cmd_report(args) -> int:
    folder = _folder(args.reading, fallback=library.latest)
    client = None if args.no_summary else OpenAICompatible.from_env()
    path = report.write(folder, client=client)
    print(path)
    if args.show:
        print(path.read_text(encoding="utf-8"))
    return 0


def cmd_records(args) -> int:
    found = library.readings()
    print(f"{library.readings_dir()}  ({len(found)} readings)")
    for folder in found:
        lesson = Lesson.load(folder / "lesson.json")
        asked = sum(1 for e in library.events(folder) if e.get("kind") == "exchange" and not e.get("review"))
        status = library.status(folder)
        print(f"  {folder.name[:10]}  {status:<8}  {asked:>2} questions  {lesson.title}")
    return 0


def cmd_telegram(args) -> int:
    import os

    from . import telegram

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("set TELEGRAM_BOT_TOKEN (from @BotFather in Telegram) in .env first")
    client = OpenAICompatible.from_env()
    if client is None:
        _log("no model key: the librarian can list and send reports, but not prepare or talk")
    try:
        telegram.run(token, client, log=_log, explain=args.explain, bedtime=not args.no_bedtime,
                     review=args.review, ask_at=args.ask_at, decide_at=args.decide_at, chat_model=args.chat_model)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_chat(args) -> int:
    """Talk with the librarian in the terminal; the same memory as Telegram, and it shows its searches."""
    from .desk import Desk

    client = OpenAICompatible.from_env()
    if client is None:
        raise SystemExit("set OPENAI_API_KEY (or MARGIN_API_KEY) in .env first")
    desk = Desk(client, language=args.explain, model=args.chat_model, log=_log)
    print(f"  (talking with {desk.model or client.model}; searches are shown indented)\n", flush=True)
    said = list(args.message)
    while True:
        if said:
            text = said.pop(0)
            print(f"you> {text}")
        elif args.message:
            return 0                                   # messages given on the command line: done
        else:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not text:
                continue
        desk.remember("reader", text)
        answer = desk.reply(text)
        for line in answer.trace:
            print("    " + line.replace("\n", "\n    "))
        print(f"librarian> {answer.text}\n", flush=True)
        if answer.text:
            desk.remember("librarian", answer.text)
        if answer.prepare:
            print(f"    (would prepare: {answer.prepare}; run: biblio prepare {answer.prepare})\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="biblio", description="Bibliothecary: a personal librarian. "
                                "Readings and reports are kept in " + str(library.readings_dir()))
    p.add_argument("--version", action="version", version=f"bibliothecary {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("prepare", help="prepare a reading: background, explanation, review questions")
    pr.add_argument("article", help="URL, .txt, .md or .html")
    margin_cli.add_build_options(pr)
    pr.set_defaults(fn=cmd_prepare)

    r = sub.add_parser("read", help="read with the librarian and keep the record (default: the next unread)")
    r.add_argument("reading", nargs="?", help="a reading folder, its name, or any lesson .json")
    margin_cli.add_serve_options(r)
    r.set_defaults(fn=cmd_read)

    rp = sub.add_parser("report", help="rewrite a reading report (default: the latest reading)")
    rp.add_argument("reading", nargs="?")
    rp.add_argument("--no-summary", action="store_true", help="do not ask a model for the summary")
    rp.add_argument("--show", action="store_true", help="print the report")
    rp.set_defaults(fn=cmd_report)

    rc = sub.add_parser("records", help="list the readings kept so far")
    rc.set_defaults(fn=cmd_records)

    tg = sub.add_parser("telegram", help="talk with the librarian in Telegram (needs TELEGRAM_BOT_TOKEN)")
    tg.add_argument("--explain", default="English", help="language it talks and explains in, e.g. 'Simplified Chinese'")
    tg.add_argument("--ask-at", default="12:00", help="when it asks what you'd like to read tonight (HH:MM)")
    tg.add_argument("--decide-at", default="19:00", help="when it settles tonight's reading (HH:MM)")
    tg.add_argument("--review", type=int, default=3, help="review questions per reading")
    tg.add_argument("--no-bedtime", action="store_true", help="no good night at the end")
    tg.add_argument("--chat-model", help="model for conversation and choosing readings "
                    "(default: $BIBLIOTHECARY_CHAT_MODEL, else the main model)")
    tg.set_defaults(fn=cmd_telegram)

    ch = sub.add_parser("chat", help="talk with the librarian here in the terminal (shares Telegram's memory)")
    ch.add_argument("message", nargs="*", help="say these one after another and stop; none = talk until Ctrl+D")
    ch.add_argument("--explain", default="English", help="language it talks in, e.g. 'Simplified Chinese'")
    ch.add_argument("--chat-model", help="as for telegram")
    ch.set_defaults(fn=cmd_chat)

    args = p.parse_args(argv)
    margin_cli.load_env()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
