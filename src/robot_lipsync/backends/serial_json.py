"""A compact, versioned JSON-lines backend for serial or socket transports."""

from __future__ import annotations

import json

from ..events import ArticulationEvent


def encode_event(event: ArticulationEvent) -> bytes:
    a = event.articulation
    payload = {
        "v": 1,
        "sid": event.session_id,
        "t": round(event.start_ms),
        "d": round(event.duration_ms),
        "p": event.viseme,
        "a": [
            round(a.jaw_open, 4),
            round(a.lip_separation, 4),
            round(a.mouth_width, 4),
            round(a.lip_round, 4),
            round(a.lip_press, 4),
            round(a.lip_protrusion, 4),
            round(a.lower_lip_tuck, 4),
            round(a.asymmetry, 4),
        ],
    }
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
