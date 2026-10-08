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
    assert "DotLips" in output.read_text(encoding="utf-8")


def test_demo_profiles_and_palettes(tmp_path):
    for profile in ("screen", "oled"):
        for palette in ("red", "blue"):
            output = tmp_path / f"{profile}-{palette}.html"
            args = ["demo", "--output", str(output), "--profile", profile, "--palette", palette]
            assert main(args) == 0
            html = output.read_text(encoding="utf-8")
            assert f"prof.value='{profile}'" in html and f"pal.value='{palette}'" in html


def test_spanish_demo_uses_spanish_profile(tmp_path):
    output = tmp_path / "spanish.html"
    assert main(["demo", "--text", "Hola, mundo.", "--language", "es", "--output", str(output)]) == 0
    events = json.loads(output.with_suffix(".timeline.json").read_text(encoding="utf-8"))
    assert any(event["viseme"] == "ES_ROUND_O" for event in events)
    assert {event["language"] for event in events} == {"es"}


def test_mandarin_demo_uses_mandarin_profile(tmp_path):
    output = tmp_path / "mandarin.html"
    assert main(["demo", "--text", "你好，世界。", "--language", "zh-CN", "--output", str(output)]) == 0
    events = json.loads(output.with_suffix(".timeline.json").read_text(encoding="utf-8"))
    assert any(event["viseme"].startswith("ZH_") for event in events)
    assert {event["language"] for event in events} == {"zh-CN"}


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
