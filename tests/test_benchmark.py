import json
import sys
from pathlib import Path

import jsonschema

from robot_lipsync.benchmark import benchmark_report, load_suite, run_jsonl_adapter

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_suite_matches_repository_fixture():
    assert load_suite() == load_suite(ROOT / "benchmarks" / "english_v1.json")


def test_stub_adapter_runs_persistently_and_checkpoints(tmp_path):
    suite = load_suite(ROOT / "benchmarks" / "english_v1.json")
    output = tmp_path / "traces.jsonl"
    result = run_jsonl_adapter(
        [sys.executable, str(ROOT / "benchmarks" / "stub_agent.py")],
        suite,
        output,
        repeats=1,
        warmups=1,
        limit=3,
        timeout_s=5,
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    schema = json.loads((ROOT / "schemas" / "latency-trace-v1.schema.json").read_text(encoding="utf-8"))
    for record in records:
        jsonschema.validate(record, schema)
    assert result["saved"] == 3
    assert len(records) == 3
    assert all(record["metadata"]["simulated"] for record in records)
    assert all(not record["metadata"]["warmup"] for record in records)


def test_benchmark_report_separates_simulated_results(tmp_path):
    suite = load_suite(ROOT / "benchmarks" / "english_v1.json")
    output = tmp_path / "traces.jsonl"
    run_jsonl_adapter(
        [sys.executable, str(ROOT / "benchmarks" / "stub_agent.py")],
        suite,
        output,
        repeats=1,
        warmups=0,
        limit=4,
        timeout_s=5,
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    report = benchmark_report(records)
    assert report["total_trials"] == 4
    assert report["successful_trials"] == 4
    assert report["simulated_trials"] == 4
    assert "physical_audio_start" in report["marks"]
    assert "audio_visual_start_offset_ms" in report
