"""Namespaced, integer serial protocol for constrained physical devices."""

from __future__ import annotations

from dataclasses import dataclass

from ..events import ArticulationEvent


def _session(value: str) -> str:
    if (
        not value
        or len(value) > 16
        or not value.isascii()
        or any(not (char.isalnum() or char in "_-") for char in value)
    ):
        raise ValueError("session id must be 1-16 ASCII letters, digits, '_' or '-'")
    return value


def _unit(value: float) -> int:
    return round(max(0.0, min(1.0, float(value))) * 1000.0)


def encode_reset(session_id: str) -> bytes:
    return f"LIP/RESET {_session(session_id)}\n".encode()


def encode_event(event: ArticulationEvent) -> bytes:
    a = event.articulation
    values = (
        _unit(a.jaw_open),
        _unit(a.lip_separation),
        _unit(a.mouth_width),
        _unit(a.lip_round),
        _unit(a.lip_press),
        _unit(a.lip_protrusion),
        _unit(a.lower_lip_tuck),
        round(max(-1.0, min(1.0, float(a.asymmetry))) * 1000.0),
        _unit(event.intensity),
    )
    fields = " ".join(str(value) for value in values)
    frame = event.metadata.get("oled_frame") if event.metadata else None
    if isinstance(frame, int) and 0 <= frame < 64:
        fields += f" {frame}"  # optional Mouth frame hint; older boards ignore it
    return (
        f"LIP/EVENT {_session(event.session_id)} {round(event.start_ms)} {max(1, round(event.duration_ms))} {fields}\n"
    ).encode()


def encode_start(session_id: str, *, delay_ms: int = 0, offset_ms: int = 0) -> bytes:
    if not 0 <= delay_ms <= 5000 or not 0 <= offset_ms <= 600_000:
        raise ValueError("delay_ms or offset_ms is outside the protocol range")
    return f"LIP/START {_session(session_id)} {delay_ms} {offset_ms}\n".encode()


def encode_count(session_id: str) -> bytes:
    return f"LIP/COUNT {_session(session_id)}\n".encode()


def encode_end(session_id: str) -> bytes:
    return f"LIP/END {_session(session_id)}\n".encode()


@dataclass(frozen=True)
class LipReply:
    level: str
    name: str
    fields: dict[str, str]


def parse_reply(line: str) -> LipReply | None:
    """Parse only the LIP namespace; unrelated shared-serial traffic is ignored."""

    parts = line.strip().split()
    if len(parts) < 2 or parts[0] not in {"LIP/OK", "LIP/ERR", "LIP/EVENT"}:
        return None
    fields = {}
    for part in parts[2:]:
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    return LipReply(parts[0][4:], parts[1], fields)
