#!/usr/bin/env python3
"""
Render a timeline JSON plan to a single video file.
Usage: python scripts/render.py plans/<name>.json output/<name>.mp4 [--captions [ass_file]] [--max-length SEC]
"""

import argparse
import sys
import tempfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from caption_style_resolve import fonts_bundle_dir  # noqa: E402
from captions import build_ass, caption_events, load_plan_data, load_segments, remap_words  # noqa: E402
from media import TimelinePiece, burn_captions, render_timeline  # noqa: E402
from timeline_format import (  # noqa: E402
    TIMELINE_GAP_SOURCE,
    is_v2,
    load_plan_file,
    v1_segments_from_data,
)
from validate_plan import validate_plan  # noqa: E402

_GAP_LABEL = "black+silence (gap)"


def resolve_source(raw: str) -> Path:
    path = Path(raw)
    if not path.is_file():
        path = Path.cwd() / raw
    if not path.is_file():
        raise FileNotFoundError(f"Source not found: {raw}")
    return path


def parse_segments(segments_raw: list[dict]) -> list[TimelinePiece]:
    pieces: list[TimelinePiece] = []
    for seg in segments_raw:
        start = float(seg["start"])
        end = float(seg["end"])
        raw = seg.get("source")
        speed = float(seg["speed"]) if seg.get("speed") is not None else 1.0
        volume = float(seg["volume"]) if seg.get("volume") is not None else 1.0
        z = seg.get("zoom")
        zoom = float(z) if z is not None else None
        if raw == TIMELINE_GAP_SOURCE:
            pieces.append(
                TimelinePiece(None, start, end, speed=1.0, volume=1.0, zoom=None)
            )
            continue
        source = resolve_source(raw)
        pieces.append(
            TimelinePiece(source, start, end, speed=speed, volume=volume, zoom=zoom)
        )
    return pieces


def load_timeline(plan_path: Path) -> list[dict]:
    data = load_plan_file(plan_path)
    return v1_segments_from_data(data)


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

    plan_data = load_plan_file(plan_path)
    try:
        segments_raw = v1_segments_from_data(plan_data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not segments_raw:
        print("Error: plan has no video segments", file=sys.stderr)
        sys.exit(1)

    if is_v2(plan_data):
        print("Timeline schema v2 (video track; gaps filled with black + silence).")

    try:
        pieces = parse_segments(segments_raw)
    except (KeyError, TypeError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Rendering {len(pieces)} segment(s) -> {output_path}")
    for i, piece in enumerate(pieces):
        label = _GAP_LABEL if piece.is_gap() else piece.path.name
        print(f"  [{i + 1}/{len(pieces)}] {label}  {piece.source_start:.2f}s - {piece.source_end:.2f}s")

    render_target = output_path
    temp_video: Path | None = None
    if args.captions is not None:
        temp_video = Path(tempfile.mkdtemp()) / "render_nocap.mp4"
        render_target = temp_video

    try:
        render_timeline(pieces, render_target)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.captions is not None:
        ass_path = (
            plan_path.with_name(plan_path.stem + "_captions.ass")
            if args.captions == "AUTO"
            else Path(args.captions)
        )
        pdata = load_plan_data(plan_path)
        segs = load_segments(plan_path)
        words = remap_words(segs, plan_data=pdata)
        events = caption_events(words, plan_data=pdata)
        tw = th = None
        if isinstance(pdata, dict) and isinstance(pdata.get("settings"), dict):
            s = pdata["settings"]
            tw = s.get("width")
            th = s.get("height")
        vw = int(tw) if isinstance(tw, (int, float)) else 1080
        vh = int(th) if isinstance(th, (int, float)) else 1920
        if not ass_path.is_file():
            print(f"Generating captions -> {ass_path}")
            ass_path.write_text(
                build_ass(words, plan_data=pdata, video_w=vw, video_h=vh),
                encoding="utf-8",
            )
        print(f"Burning subtitles ({len(events)} events): {ass_path}")
        try:
            burn_captions(
                render_target,
                output_path,
                events,
                ass_path=ass_path,
                fonts_dir=fonts_bundle_dir(),
            )
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        if temp_video and temp_video.is_file():
            temp_video.unlink()

    print(f"Done: {output_path}")


if __name__ == "__main__":
    main()
