import json
from pathlib import Path

import jsonschema

from robot_lipsync.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_demo_writes_html_and_timeline(tmp_path):
    output = tmp_path / "demo.html"
    assert main(["demo", "--output", str(output)]) == 0
    assert output.exists()
    assert output.with_suffix(".timeline.json").exists()
    assert "MUSCLE" not in output.read_text(encoding="utf-8")
    assert "articulation" in output.read_text(encoding="utf-8")


def test_compile_fixture_validates_against_schema(tmp_path):
    output = tmp_path / "timeline.json"
    fixture = ROOT / "examples" / "good_evening.alignment.json"
    assert main(["compile", str(fixture), "--output", str(output)]) == 0
    events = json.loads(output.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "articulation-event-v1.schema.json").read_text(encoding="utf-8"))
    for event in events:
        jsonschema.validate(event, schema)


def test_reference_traces_validate_and_report(capsys):
    traces = ROOT / "examples" / "reference_traces.jsonl"
    schema = json.loads((ROOT / "schemas" / "latency-trace-v1.schema.json").read_text(encoding="utf-8"))
    for line in traces.read_text(encoding="utf-8").splitlines():
        jsonschema.validate(json.loads(line), schema)
    assert main(["report", str(traces)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["samples"] == 8
    assert report["max_ms"] == 4573
