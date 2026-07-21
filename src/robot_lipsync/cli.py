"""Command-line interface for offline compilation, preview, and latency reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .metrics import summarize_traces
from .phonemes import alignment_to_phonemes
from .planner import phonemes_to_articulation
from .providers.offline import load_alignment, synthetic_alignment
from .renderers import render_html

DEMO_TEXT = "Good evening. How charming."


def compile_spans(spans, *, session_id: str = "offline-demo"):
    phonemes = alignment_to_phonemes(spans)
    return phonemes_to_articulation(session_id, phonemes)


def _write_timeline(events, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([event.to_dict() for event in events], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def command_demo(args) -> int:
    spans = synthetic_alignment(args.text)
    events = compile_spans(spans)
    output = render_html(events, args.output, title="Robot LipSync — no-key demo")
    timeline = output.with_suffix(".timeline.json")
    _write_timeline(events, timeline)
    print(f"HTML preview: {output.resolve()}")
    print(f"Timeline JSON: {timeline.resolve()}")
    return 0


def command_compile(args) -> int:
    _, spans = load_alignment(args.alignment)
    events = compile_spans(spans, session_id=args.session_id)
    _write_timeline(events, Path(args.output))
    print(f"Wrote {len(events)} articulation events to {Path(args.output).resolve()}")
    return 0


def command_report(args) -> int:
    records = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = summarize_traces(records, mark=args.mark)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robot-lipsync", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="create a no-key animated HTML preview")
    demo.add_argument("--text", default=DEMO_TEXT)
    demo.add_argument("--output", default="build/demo.html")
    demo.set_defaults(func=command_demo)

    compile_parser = subparsers.add_parser("compile", help="compile an alignment fixture to Articulation IR")
    compile_parser.add_argument("alignment")
    compile_parser.add_argument("--output", default="build/timeline.json")
    compile_parser.add_argument("--session-id", default="offline-fixture")
    compile_parser.set_defaults(func=command_compile)

    report = subparsers.add_parser("report", help="summarize JSONL latency traces")
    report.add_argument("input")
    report.add_argument("--mark", default="physical_audio_start")
    report.set_defaults(func=command_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
