#!/usr/bin/env python3
"""
Render a timeline JSON plan to a single video file.
Usage: python scripts/render.py plans/<name>.json output/<name>.mp4 [--captions [ass_file]] [--max-length SEC]
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from captions import build_ass, caption_events, load_segments, remap_words  # noqa: E402
from media import burn_captions, render_timeline  # noqa: E402
from validate_plan import validate_plan  # noqa: E402


def resolve_source(raw: str) -> Path:
    path = Path(raw)
    if not path.is_file():
        path = Path.cwd() / raw
    if not path.is_file():
        raise FileNotFoundError(f"Source not found: {raw}")
    return path


def parse_segments(segments_raw: list[dict]) -> list[tuple[Path, float, float]]:
    segments: list[tuple[Path, float, float]] = []
    for i, seg in enumerate(segments_raw):
        source = resolve_source(seg["source"])
        start = float(seg["start"])
        end = float(seg["end"])
        segments.append((source, start, end))
    return segments


def load_timeline(plan_path: Path) -> list[dict]:
    data = json.loads(plan_path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "segments" in data:
        return data["segments"]
    raise ValueError("Plan JSON must be a list or an object with 'segments'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a timeline plan to video")
    parser.add_argument("plan_path")
    parser.add_argument("output_path")
    parser.add_argument(
        "--captions",
        nargs="?",
        const="AUTO",
        default=None,
        help="Burn ASS subtitles (optional path; default: <plan>_captions.ass)",
    )
    parser.add_argument(
        "--max-length",
        type=float,
        default=None,
        help="Validate total output duration does not exceed this",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan_path)
    output_path = Path(args.output_path)

    if not plan_path.is_file():
        print(f"Error: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    errors = validate_plan(plan_path, args.max_length)
    if errors:
        print("Plan validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    try:
        segments_raw = load_timeline(plan_path)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not segments_raw:
        print("Error: plan has no segments", file=sys.stderr)
        sys.exit(1)

    try:
        segments = parse_segments(segments_raw)
    except (KeyError, TypeError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Rendering {len(segments)} segment(s) -> {output_path}")
    for i, (src, start, end) in enumerate(segments):
        print(f"  [{i + 1}/{len(segments)}] {src.name}  {start:.2f}s - {end:.2f}s")

    render_target = output_path
    temp_video: Path | None = None
    if args.captions is not None:
        temp_video = Path(tempfile.mkdtemp()) / "render_nocap.mp4"
        render_target = temp_video

    try:
        render_timeline(segments, render_target)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.captions is not None:
        ass_path = (
            plan_path.with_name(plan_path.stem + "_captions.ass")
            if args.captions == "AUTO"
            else Path(args.captions)
        )
        words = remap_words(load_segments(plan_path))
        events = caption_events(words)
        if not ass_path.is_file():
            print(f"Generating captions -> {ass_path}")
            ass_path.write_text(build_ass(words), encoding="utf-8")
        print(f"Burning subtitles ({len(events)} events): {ass_path}")
        try:
            burn_captions(render_target, output_path, events, ass_path=ass_path)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        if temp_video and temp_video.is_file():
            temp_video.unlink()

    print(f"Done: {output_path}")


if __name__ == "__main__":
    main()
