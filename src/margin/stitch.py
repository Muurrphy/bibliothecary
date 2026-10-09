"""Join the lines kept by MARGIN_RECORD_DIR into one track on the real timeline.

    python -m margin.stitch <folder> [-o all.m4a]

Silence fills the gaps, an interrupted line is cut where it stopped, and the track starts at
the first line, so in a video editor it needs lining up once. Needs ffmpeg."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def lines(folder: Path) -> list[dict]:
    out = []
    for raw in (folder / "timeline.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if (folder / item["file"]).is_file():
            out.append(item)
    return sorted(out, key=lambda x: x["start"])


def stitch(folder: Path, output: Path) -> Path:
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is needed (brew install ffmpeg)")
    found = lines(folder)
    if not found:
        raise SystemExit(f"nothing recorded in {folder}")
    t0 = found[0]["start"]
    inputs, filters = [], []
    for i, item in enumerate(found):
        inputs += ["-i", str(folder / item["file"])]
        length = max(0.05, item["end"] - item["start"])
        delay = int((item["start"] - t0) * 1000)
        filters.append(f"[{i}:a]atrim=0:{length:.3f},adelay={delay}|{delay}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(found)))
    graph = ";".join(filters) + f";{mix}amix=inputs={len(found)}:normalize=0[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
                    "-map", "[out]", str(output)], check=True)
    return output


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="margin-stitch", description=__doc__.splitlines()[0])
    p.add_argument("folder")
    p.add_argument("-o", "--output", help="default: <folder>/all.m4a")
    args = p.parse_args(argv)
    folder = Path(args.folder).expanduser()
    out = stitch(folder, Path(args.output) if args.output else folder / "all.m4a")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
