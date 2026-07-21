"""Generate PCM and an articulation preview from one ElevenLabs HTTP stream.

Usage:
    pip install -e ".[elevenlabs]"
    export ELEVENLABS_API_KEY=...
    export ELEVENLABS_VOICE_ID=...
    python examples/elevenlabs_http.py "Good evening. How charming."

The API key is read from the environment and is never written to output files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from robot_lipsync import IncrementalArticulationCompiler, LatencyTrace
from robot_lipsync.providers.elevenlabs import ElevenLabsHttpProvider, prewarm
from robot_lipsync.renderers import render_html


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} before running this example.")
    return value


def main() -> int:
    text = " ".join(sys.argv[1:]).strip() or "Good evening. How charming."
    api_key = required_environment("ELEVENLABS_API_KEY")
    voice_id = required_environment("ELEVENLABS_VOICE_ID")

    build = Path("build")
    build.mkdir(exist_ok=True)
    pcm_path = build / "elevenlabs.pcm"
    timeline_path = build / "elevenlabs.timeline.json"
    html_path = build / "elevenlabs.html"

    trace = LatencyTrace()
    compiler = IncrementalArticulationCompiler(trace.session_id)
    provider = ElevenLabsHttpProvider(api_key=api_key, voice_id=voice_id)
    connection_ms = prewarm(api_key)

    events = []
    sample_rate = 24_000
    with pcm_path.open("wb") as pcm:
        for chunk in provider.stream(text, trace=trace):
            sample_rate = chunk.sample_rate
            if chunk.pcm:
                pcm.write(chunk.pcm)
            events.extend(compiler.append(list(chunk.alignment), final=chunk.is_final))

    timeline_path.write_text(
        json.dumps([event.to_dict() for event in events], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    render_html(events, html_path, title="Robot LipSync — ElevenLabs stream")
    print(f"Connection prewarm: {connection_ms:.1f} ms")
    print(f"PCM: {pcm_path} ({sample_rate} Hz, signed 16-bit little-endian mono)")
    print(f"Timeline: {timeline_path}")
    print(f"Preview: {html_path}")
    print(trace.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
