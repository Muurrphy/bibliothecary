"""Deterministic JSONL benchmark adapter used only for CI and runner tests."""

from __future__ import annotations

import hashlib
import json
import sys


def write(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    if request.get("type") == "hello":
        write({"type": "ready", "protocol": 1, "adapter": "deterministic-stub"})
        continue
    if request.get("type") == "shutdown":
        break
    if request.get("type") != "trial":
        write({"type": "error", "error": "unknown request", "trial_id": request.get("trial_id")})
        continue

    trial_id = str(request["trial_id"])
    seed = int(hashlib.sha256(trial_id.encode()).hexdigest()[:8], 16)
    llm = 480 + seed % 520
    phrase = llm + 110 + (seed // 11) % 240
    tts_headers = phrase + 90 + (seed // 23) % 120
    first_audio = tts_headers + 70 + (seed // 41) % 90
    physical = first_audio + 260 + (seed // 71) % 240
    if seed % 29 == 0:
        physical += 1900
    visible = physical - 42 + (seed % 31)
    trace = {
        "schema": "robot-lipsync/latency-trace/v1",
        "session_id": trial_id,
        "milliseconds": {
            "end_of_user_speech": 0,
            "turn_committed": 30,
            "llm_first_token": llm,
            "phrase_committed": phrase,
            "tts_request_start": phrase + 2,
            "tts_response_headers": tts_headers,
            "tts_first_audio": first_audio,
            "device_first_audio_chunk": first_audio + 35,
            "physical_audio_start": physical,
            "first_visible_motion": visible,
        },
        "counters": {"underruns": 0, "dropped_motion_events": 0},
        "metadata": {"simulated": True, "adapter": "deterministic-stub"},
    }
    write({"type": "trace", "trial_id": trial_id, "trace": trace})
