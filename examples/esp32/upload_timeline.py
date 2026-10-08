"""Compile a fixture and play it on the reference ESP32/OLED firmware."""

from __future__ import annotations

import argparse
import time

from robot_lipsync.backends import SerialTimelineClient
from robot_lipsync.cli import compile_spans
from robot_lipsync.providers import load_alignment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", help="for example /dev/cu.usbmodem1101 or COM5")
    parser.add_argument("--alignment", default="examples/good_evening.alignment.json")
    args = parser.parse_args()

    try:
        import serial
    except ImportError as error:
        raise SystemExit('Install the hardware extra first: pip install -e ".[serial]"') from error

    _, spans = load_alignment(args.alignment)
    events = compile_spans(spans, session_id="fixture-01")
    with serial.Serial(args.port, 115200, timeout=0.1) as port:
        time.sleep(1.5)
        port.reset_input_buffer()
        client = SerialTimelineClient(port, timeout_s=2.0)
        capacity = client.reset("fixture-01")
        if len(events) > capacity:
            raise SystemExit(f"Timeline has {len(events)} events but device capacity is {capacity}.")
        uploaded = client.append(events, confirm=True)
        if uploaded != len(events):
            raise SystemExit(f"Device reports {uploaded} events after uploading {len(events)}.")
        reply = client.start("fixture-01", delay_ms=250)
        print(f"Started {uploaded} events: {reply.fields}")
        duration_s = max(event.start_ms + event.duration_ms for event in events) / 1000.0
        time.sleep(duration_s + 0.5)
        client.end("fixture-01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
