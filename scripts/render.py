#!/usr/bin/env python3
"""
Render a timeline JSON plan to a single video file.
Usage: python scripts/render.py plans/<name>.json output/<name>.mp4
"""

import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from media import render_timeline, video_duration_seconds  # noqa: E402


def load_timeline(plan_path: Path) -> list[dict]:
    data = json.loads(plan_path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "segments" in data:
        return data["segments"]
    raise ValueError("Plan JSON must be a list or an object with 'segments'")


def resolve_source(raw: str) -> Path:
    path = Path(raw)
    if not path.is_file():
        path = Path.cwd() / raw
    if not path.is_file():
        raise FileNotFoundError(f"Source not found: {raw}")
    return path


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: python scripts/render.py plans/<plan>.json output/<out>.mp4",
            file=sys.stderr,
        )
        sys.exit(1)

    plan_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not plan_path.is_file():
        print(f"Error: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    try:
        segments_raw = load_timeline(plan_path)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not segments_raw:
        print("Error: plan has no segments", file=sys.stderr)
        sys.exit(1)

    segments: list[tuple[Path, float, float]] = []
    for i, seg in enumerate(segments_raw):
        try:
            source = resolve_source(seg["source"])
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError) as e:
            print(f"Error: bad segment {i}: {e}", file=sys.stderr)
            sys.exit(1)
        if start >= end:
            print(f"Error: segment {i} has start >= end", file=sys.stderr)
            sys.exit(1)
        total = video_duration_seconds(source)
        if end > total + 0.02:
            print(
                f"Error: segment {i} end {end}s past source duration {total:.3f}s",
                file=sys.stderr,
            )
            sys.exit(1)
        segments.append((source, start, end))

    print(f"Rendering {len(segments)} segment(s) -> {output_path}")
    for i, (src, start, end) in enumerate(segments):
        print(f"  [{i + 1}/{len(segments)}] {src.name}  {start:.2f}s - {end:.2f}s")

    try:
        render_timeline(segments, output_path)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Done: {output_path}")


if __name__ == "__main__":
    main()
