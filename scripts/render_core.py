"""
Render a timeline plan (dict or path) to MP4 without CLI.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from captions import build_ass, caption_events, load_segments, remap_words
from media import TimelinePiece, burn_captions, render_timeline
from timeline_format import (
    TIMELINE_GAP_SOURCE,
    is_v2,
    load_plan_file,
    v1_segments_from_data,
)
from validate_plan import validate_plan_data


def resolve_source(raw: str, root: Path) -> Path:
    path = Path(raw)
    if path.is_file():
        return path
    path = root / raw
    if path.is_file():
        return path
    raise FileNotFoundError(f"Source not found: {raw}")


def _segment_transform(seg: dict) -> tuple[float, float, float | None]:
    speed = float(seg["speed"]) if seg.get("speed") is not None else 1.0
    volume = float(seg["volume"]) if seg.get("volume") is not None else 1.0
    z = seg.get("zoom")
    zoom = float(z) if z is not None else None
    return speed, volume, zoom


def parse_segments(segments_raw: list[dict], root: Path) -> list[TimelinePiece]:
    pieces: list[TimelinePiece] = []
    for seg in segments_raw:
        start = float(seg["start"])
        end = float(seg["end"])
        raw = seg.get("source")
        if raw == TIMELINE_GAP_SOURCE:
            pieces.append(
                TimelinePiece(
                    None, start, end, speed=1.0, volume=1.0, zoom=None
                )
            )
            continue
        speed, volume, zoom = _segment_transform(seg)
        source = resolve_source(raw, root)
        pieces.append(
            TimelinePiece(source, start, end, speed=speed, volume=volume, zoom=zoom)
        )
    return pieces


def render_plan_data(
    plan_data: dict,
    output_path: Path,
    *,
    root: Path,
    captions: bool = False,
    max_length: float | None = None,
    plan_path_for_captions: Path | None = None,
) -> None:
    """Validate and render v1 or v2 plan dict to output_path."""
    errors = validate_plan_data(plan_data, max_length)
    if errors:
        raise ValueError(errors)

    segments_raw = v1_segments_from_data(plan_data)
    if not segments_raw:
        raise ValueError("Plan has no video segments.")

    segments = parse_segments(segments_raw, root)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    render_target = output_path
    temp_video: Path | None = None
    if captions:
        temp_video = Path(tempfile.mkdtemp()) / "render_nocap.mp4"
        render_target = temp_video

    render_timeline(segments, render_target)

    if captions:
        cap_plan = plan_path_for_captions
        if cap_plan is None:
            raise ValueError("captions=True requires plan_path_for_captions")
        ass_path = cap_plan.with_name(cap_plan.stem + "_captions.ass")
        words = remap_words(load_segments(cap_plan))
        events = caption_events(words)
        if not ass_path.is_file():
            ass_path.write_text(build_ass(words), encoding="utf-8")
        burn_captions(render_target, output_path, events, ass_path=ass_path)
        if temp_video and temp_video.is_file():
            temp_video.unlink()
    elif is_v2(plan_data):
        pass  # v2 without captions — already wrote to output_path


def render_plan_file(
    plan_path: Path,
    output_path: Path,
    *,
    root: Path | None = None,
    captions: bool = False,
    max_length: float | None = None,
) -> None:
    root = root or Path.cwd()
    plan_data = load_plan_file(plan_path)
    render_plan_data(
        plan_data,
        output_path,
        root=root,
        captions=captions,
        max_length=max_length,
        plan_path_for_captions=plan_path if captions else None,
    )
