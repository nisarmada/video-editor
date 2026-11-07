"""
Render a timeline plan (dict or path) to MP4 without CLI.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from caption_style_resolve import fonts_bundle_dir
from captions import build_ass, caption_events, load_plan_data, load_segments, remap_words
from media import AudioBranch, TimelinePiece, burn_captions, render_timeline
from timeline_format import (
    TIMELINE_GAP_SOURCE,
    get_tracks,
    is_v2,
    load_plan_file,
    v1_segments_from_data,
    v2_timeline_duration,
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


def _optional_float(seg: dict, key: str) -> float | None:
    if seg.get(key) is None:
        return None
    try:
        return float(seg[key])
    except (TypeError, ValueError):
        return None


def _optional_transition(seg: dict) -> dict | None:
    tr = seg.get("transition_out")
    return tr if isinstance(tr, dict) else None


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
        embed_silent = bool(seg.get("embed_audio_silent"))
        if raw == TIMELINE_GAP_SOURCE:
            pieces.append(
                TimelinePiece(
                    None,
                    start,
                    end,
                    speed=1.0,
                    volume=1.0,
                    zoom=None,
                    embed_audio_silent=False,
                )
            )
            continue
        speed, volume, zoom = _segment_transform(seg)
        source = resolve_source(raw, root)
        pieces.append(
            TimelinePiece(
                source,
                start,
                end,
                speed=speed,
                volume=volume,
                zoom=zoom,
                audio_fade_in=_optional_float(seg, "audio_fade_in"),
                audio_fade_out=_optional_float(seg, "audio_fade_out"),
                video_fade_in=_optional_float(seg, "video_fade_in"),
                video_fade_out=_optional_float(seg, "video_fade_out"),
                transition_out=_optional_transition(seg),
                embed_audio_silent=embed_silent,
            )
        )
    return pieces


def collect_audio_branches(plan_data: dict, root: Path) -> list[AudioBranch]:
    """Non-muted audio-track clips, sorted by timeline_start."""
    if not is_v2(plan_data):
        return []
    out: list[AudioBranch] = []
    for tr in get_tracks(plan_data, "audio"):
        if tr.get("muted"):
            continue
        track_vol = (
            float(tr["volume"])
            if tr.get("volume") is not None
            else 1.0
        )
        duck_under = tr.get("duck_under_track_id")
        duck_gain = (
            float(tr["duck_gain"]) if tr.get("duck_gain") is not None else None
        )
        clips = sorted(
            tr.get("clips") or [],
            key=lambda c: float(c["timeline_start"]),
        )
        for c in clips:
            raw = c.get("source")
            if not raw:
                continue
            try:
                path = resolve_source(str(raw), root)
            except FileNotFoundError:
                continue
            speed = float(c.get("speed") or 1.0) or 1.0
            clip_vol = float(c.get("volume")) if c.get("volume") is not None else 1.0
            volume = clip_vol * track_vol
            out.append(
                AudioBranch(
                    path=path,
                    source_start=float(c["source_in"]),
                    source_end=float(c["source_out"]),
                    speed=speed,
                    volume=volume,
                    timeline_start=float(c["timeline_start"]),
                    audio_fade_in=_optional_float(c, "audio_fade_in"),
                    audio_fade_out=_optional_float(c, "audio_fade_out"),
                    source_track_id=str(tr.get("id") or ""),
                    duck_under_track_id=(
                        str(duck_under) if isinstance(duck_under, str) and duck_under.strip() else None
                    ),
                    duck_gain=duck_gain,
                )
            )
    return out


def render_plan_data(
    plan_data: dict,
    output_path: Path,
    *,
    root: Path,
    captions: bool = False,
    max_length: float | None = None,
    plan_path_for_captions: Path | None = None,
    cancel_event: threading.Event | None = None,
    on_timeline_progress: Callable[[float | None], None] | None = None,
) -> None:
    """Validate and render v1 or v2 plan dict to output_path."""
    errors, _warnings = validate_plan_data(plan_data, max_length)
    if errors:
        raise ValueError(errors)

    segments_raw = v1_segments_from_data(plan_data)
    if not segments_raw:
        raise ValueError("Plan has no video segments.")

    segments = parse_segments(segments_raw, root)
    audio_branches: list[AudioBranch] = (
        collect_audio_branches(plan_data, root) if is_v2(plan_data) else []
    )
    timeline_total = v2_timeline_duration(plan_data) if is_v2(plan_data) else None
    output_path.parent.mkdir(parents=True, exist_ok=True)

    render_target = output_path
    temp_video: Path | None = None
    if captions:
        temp_video = Path(tempfile.mkdtemp()) / "render_nocap.mp4"
        render_target = temp_video

    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Render cancelled")

    render_timeline(
        segments,
        render_target,
        audio_branches=audio_branches if audio_branches else None,
        timeline_total=timeline_total,
        cancel_event=cancel_event,
        on_progress=on_timeline_progress,
    )

    if captions:
        cap_plan = plan_path_for_captions
        if cap_plan is None:
            raise ValueError("captions=True requires plan_path_for_captions")
        ass_path = cap_plan.with_name(cap_plan.stem + "_captions.ass")
        plan_file_data = load_plan_data(cap_plan)
        segs = load_segments(cap_plan)
        words = remap_words(segs, plan_data=plan_file_data)
        events = caption_events(words, plan_data=plan_file_data)
        tw = th = None
        if isinstance(plan_file_data, dict) and isinstance(
            plan_file_data.get("settings"), dict
        ):
            s = plan_file_data["settings"]
            tw = s.get("width")
            th = s.get("height")
        vw = int(tw) if isinstance(tw, (int, float)) else 1080
        vh = int(th) if isinstance(th, (int, float)) else 1920
        if not ass_path.is_file():
            ass_path.write_text(
                build_ass(words, plan_data=plan_file_data, video_w=vw, video_h=vh),
                encoding="utf-8",
            )
        burn_captions(
            render_target,
            output_path,
            events,
            ass_path=ass_path,
            fonts_dir=fonts_bundle_dir(),
        )
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
    cancel_event: threading.Event | None = None,
    on_timeline_progress: Callable[[float | None], None] | None = None,
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
        cancel_event=cancel_event,
        on_timeline_progress=on_timeline_progress,
    )
