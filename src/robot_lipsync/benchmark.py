"""Reproducible multi-turn benchmark runner for long-lived voice-agent adapters."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from importlib.resources import files
from itertools import pairwise
from pathlib import Path
from typing import TextIO

from .metrics import STANDARD_MARKS, summarize_traces


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    user_text: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkSuite:
    suite_id: str
    language: str
    measurement_scope: str
    cases: tuple[BenchmarkCase, ...]


def load_suite(path: str | Path | None = None) -> BenchmarkSuite:
    source = Path(path) if path is not None else files("robot_lipsync").joinpath("data/english_v1.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    cases = tuple(
        BenchmarkCase(str(item["id"]), str(item["user_text"]), tuple(str(tag) for tag in item.get("tags", [])))
        for item in data["cases"]
    )
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("benchmark suite must contain unique cases")
    return BenchmarkSuite(
        str(data["suite_id"]),
        str(data.get("language", "und")),
        str(data.get("measurement_scope", "unspecified")),
        cases,
    )


def _read_lines(stream: TextIO, output: queue.Queue[str | None]) -> None:
    try:
        for line in stream:
            if line.strip():
                output.put(line)
    finally:
        output.put(None)


def _receive(lines: queue.Queue[str | None], timeout_s: float) -> dict:
    try:
        line = lines.get(timeout=timeout_s)
    except queue.Empty as error:
        raise TimeoutError(f"adapter produced no JSON response within {timeout_s:g}s") from error
    if line is None:
        raise RuntimeError("adapter exited before producing a response")
    try:
        return json.loads(line)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"adapter stdout must be JSONL, got: {line[:160]!r}") from error


def _receive_trial(lines: queue.Queue[str | None], trial_id: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"adapter produced no response for {trial_id} within {timeout_s:g}s")
        response = _receive(lines, remaining)
        if response.get("trial_id") == trial_id:
            return response


def _write(process: subprocess.Popen, message: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _failure_trace(trial_id: str, reason: str) -> dict:
    return {
        "schema": "robot-lipsync/latency-trace/v1",
        "session_id": trial_id,
        "milliseconds": {},
        "counters": {"trial_failures": 1},
        "metadata": {"error": reason},
    }


def _validate_trace(trace: dict) -> None:
    required = {"schema", "session_id", "milliseconds", "counters", "metadata"}
    if not required.issubset(trace) or trace["schema"] != "robot-lipsync/latency-trace/v1":
        raise ValueError("adapter returned an invalid latency trace")
    if not isinstance(trace["milliseconds"], dict) or not isinstance(trace["metadata"], dict):
        raise ValueError("trace milliseconds and metadata must be objects")


def run_jsonl_adapter(
    command: list[str],
    suite: BenchmarkSuite,
    output: str | Path,
    *,
    repeats: int = 5,
    warmups: int = 3,
    limit: int | None = None,
    timeout_s: float = 45.0,
    resume: bool = False,
) -> dict:
    """Run a persistent adapter process and checkpoint every completed trial."""

    if repeats < 1 or warmups < 0 or not command:
        raise ValueError("invalid benchmark configuration")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    completed: set[str] = set()
    if resume and output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                trial_id = json.loads(line).get("metadata", {}).get("trial_id")
                if trial_id:
                    completed.add(str(trial_id))
    elif output.exists():
        output.unlink()

    trials = []
    for repetition in range(1, repeats + 1):
        for case in suite.cases:
            trials.append((f"{case.case_id}-r{repetition:02d}", repetition, case))
    if limit is not None:
        trials = trials[:limit]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_read_lines, args=(process.stdout, lines), daemon=True).start()
    run_id = uuid.uuid4().hex[:12]
    saved = 0
    failures = 0
    try:
        _write(process, {"type": "hello", "protocol": 1, "suite_id": suite.suite_id, "run_id": run_id})
        ready = _receive(lines, timeout_s)
        if ready.get("type") != "ready" or ready.get("protocol") != 1:
            raise RuntimeError("adapter did not complete the v1 hello handshake")

        warmup_cases = [suite.cases[index % len(suite.cases)] for index in range(warmups)]
        scheduled = [(f"warmup-{index + 1}", 0, case, True) for index, case in enumerate(warmup_cases)]
        scheduled.extend((trial_id, repetition, case, False) for trial_id, repetition, case in trials)
        with output.open("a", encoding="utf-8") as destination:
            for trial_id, repetition, case, is_warmup in scheduled:
                if not is_warmup and trial_id in completed:
                    continue
                request = {
                    "type": "trial",
                    "trial_id": trial_id,
                    "case_id": case.case_id,
                    "user_text": case.user_text,
                    "tags": list(case.tags),
                    "warmup": is_warmup,
                }
                _write(process, request)
                started = time.monotonic()
                try:
                    response = _receive_trial(lines, trial_id, timeout_s)
                    if response.get("type") != "trace":
                        raise RuntimeError(str(response.get("error") or "adapter returned no trace"))
                    trace = response["trace"]
                    _validate_trace(trace)
                except Exception as error:  # preserve failures in the raw result set
                    trace = _failure_trace(trial_id, f"{type(error).__name__}: {error}")
                    failures += 1
                trace["metadata"].update(
                    {
                        "benchmark_run_id": run_id,
                        "suite_id": suite.suite_id,
                        "trial_id": trial_id,
                        "case_id": case.case_id,
                        "case_tags": ",".join(case.tags),
                        "language": suite.language,
                        "repetition": repetition,
                        "measurement_scope": suite.measurement_scope,
                        "runner_wall_ms": round((time.monotonic() - started) * 1000.0, 3),
                        "warmup": is_warmup,
                    }
                )
                if not is_warmup:
                    destination.write(json.dumps(trace, ensure_ascii=False, separators=(",", ":")) + "\n")
                    destination.flush()
                    saved += 1
        _write(process, {"type": "shutdown"})
    finally:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=2)
    return {"run_id": run_id, "scheduled": len(trials), "saved": saved, "failures": failures, "output": str(output)}


def benchmark_report(records: list[dict]) -> dict:
    """Summarize stages, failure rate, audio quality, and A/V start offset."""

    real_records = [record for record in records if not record.get("metadata", {}).get("warmup")]
    successful = [record for record in real_records if "physical_audio_start" in record.get("milliseconds", {})]
    report: dict = {
        "total_trials": len(real_records),
        "successful_trials": len(successful),
        "failed_trials": len(real_records) - len(successful),
        "success_rate": len(successful) / len(real_records) if real_records else 0.0,
        "simulated_trials": sum(bool(record.get("metadata", {}).get("simulated")) for record in real_records),
        "measurement_scopes": dict(
            Counter(str(record.get("metadata", {}).get("measurement_scope", "unknown")) for record in real_records)
        ),
        "marks": {},
        "segments": {},
        "counters": {},
    }
    for mark in STANDARD_MARKS:
        if any(mark in record.get("milliseconds", {}) for record in real_records):
            report["marks"][mark] = summarize_traces(real_records, mark)

    for first, second in pairwise(STANDARD_MARKS):
        deltas = []
        for record in real_records:
            marks = record.get("milliseconds", {})
            if first in marks and second in marks:
                deltas.append(float(marks[second]) - float(marks[first]))
        if deltas:
            synthetic = [{"milliseconds": {"delta": value}} for value in deltas]
            report["segments"][f"{first}->{second}"] = summarize_traces(synthetic, "delta")

    if successful and any("first_visible_motion" in record.get("milliseconds", {}) for record in successful):
        offsets = []
        for record in successful:
            marks = record.get("milliseconds", {})
            if "first_visible_motion" in marks:
                offsets.append(float(marks["first_visible_motion"]) - float(marks["physical_audio_start"]))
        synthetic = [{"milliseconds": {"offset": value}} for value in offsets]
        report["audio_visual_start_offset_ms"] = summarize_traces(synthetic, "offset")

    counters: dict[str, list[float]] = defaultdict(list)
    for record in real_records:
        for name, value in record.get("counters", {}).items():
            counters[name].append(float(value))
    report["counters"] = {
        name: {"sum": sum(values), "max": max(values), "nonzero_trials": sum(value != 0 for value in values)}
        for name, values in sorted(counters.items())
    }
    return report
