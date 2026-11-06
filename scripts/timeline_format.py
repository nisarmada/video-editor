"""
Load timeline plans v1 (flat segments) and v2 (multi-track).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_V2 = 2
MIN_CLIP_SECONDS = 0.3
TRACK_TYPES = frozenset({"video", "audio", "caption"})
CREATED_BY = frozenset({"user", "ai"})

# Marker source for v1-style segments that stand for timeline gaps (export / captions cursor).
TIMELINE_GAP_SOURCE = "__timeline_gap__"


def load_plan_data(data: dict | list) -> dict | list:
    """Parse JSON already loaded."""
    return data


def load_plan_file(path: Path) -> dict | list:
    return json.loads(path.read_text())


def is_v2(data: dict | list) -> bool:
    return isinstance(data, dict) and data.get("schema_version") == SCHEMA_V2


def v1_segments_from_data(data: dict | list) -> list[dict]:
    """Normalize v1 to segment dicts with source, start, end."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "segments" in data:
        return data["segments"]
    if is_v2(data):
        return flatten_v2_to_v1_segments(data)
    raise ValueError("Plan must be v1 segments, v1 object, or schema_version 2")


def clip_timeline_duration(clip: dict, track_type: str) -> float:
    speed = float(clip.get("speed") or 1.0)
    if speed <= 0:
        speed = 1.0
    src_in = float(clip["source_in"])
    src_out = float(clip["source_out"])
    base = src_out - src_in
    if track_type == "caption":
        return base
    return base / speed


def flatten_v2_to_v1_segments(data: dict) -> list[dict]:
    """
    Flatten v2 video track to v1-style segments for render/captions.
    Sorted by timeline_start; gaps become synthetic segments (TIMELINE_GAP_SOURCE)
    so export matches preview duration (black video + silence).
    """
    video = get_track(data, "video")
    if video is None:
        return []
    ttype = "video"
    clips = sorted(video.get("clips") or [], key=lambda c: float(c["timeline_start"]))
    segments: list[dict] = []
    timeline_cursor = 0.0
    for c in clips:
        t0 = float(c["timeline_start"])
        dur = clip_timeline_duration(c, ttype)
        gap = t0 - timeline_cursor
        if gap > 0.001:
            segments.append(
                {
                    "source": TIMELINE_GAP_SOURCE,
                    "start": 0.0,
                    "end": gap,
                    "_gap": True,
                }
            )
        seg = {
            "source": c["source"],
            "start": float(c["source_in"]),
            "end": float(c["source_out"]),
        }
        if c.get("caption"):
            seg["caption"] = c["caption"]
        if c.get("text"):
            seg["caption"] = c.get("text")
        if c.get("zoom") is not None:
            seg["zoom"] = c["zoom"]
        if c.get("speed") is not None:
            seg["speed"] = float(c["speed"])
        if c.get("volume") is not None:
            seg["volume"] = float(c["volume"])
        segments.append(seg)
        timeline_cursor = t0 + dur
    return segments


def get_track(data: dict, track_type: str) -> dict | None:
    for t in data.get("tracks") or []:
        if t.get("type") == track_type:
            return t
    return None


def plan_target_length(data: dict | list) -> float | None:
    if isinstance(data, dict):
        t = data.get("target_length_seconds")
        if t is not None:
            return float(t)
        if is_v2(data):
            return v2_timeline_duration(data)
    return None


def v2_timeline_duration(data: dict) -> float:
    """End time of the last clip on any track."""
    end = 0.0
    for track in data.get("tracks") or []:
        ttype = track.get("type", "video")
        for clip in track.get("clips") or []:
            start = float(clip["timeline_start"])
            dur = clip_timeline_duration(clip, ttype)
            end = max(end, start + dur)
    return end


def validate_v2_clips_on_track(
    track: dict,
    resolve_source,
    video_duration_fn,
) -> list[str]:
    errors: list[str] = []
    ttype = track.get("type")
    tid = track.get("id", ttype)
    clips = track.get("clips") or []

    intervals: list[tuple[float, float, str]] = []

    for i, clip in enumerate(clips):
        label = f"Track {tid} clip {i}"
        for field in ("id", "timeline_start", "created_by"):
            if field not in clip:
                errors.append(f"{label}: missing '{field}'.")
        if clip.get("created_by") not in CREATED_BY:
            errors.append(f"{label}: created_by must be 'user' or 'ai'.")

        if ttype in ("video", "audio"):
            for field in ("source", "source_in", "source_out"):
                if field not in clip:
                    errors.append(f"{label}: missing '{field}'.")
                    break
            else:
                try:
                    src_in = float(clip["source_in"])
                    src_out = float(clip["source_out"])
                except (TypeError, ValueError):
                    errors.append(f"{label}: source_in/source_out must be numbers.")
                    continue
                if src_in >= src_out:
                    errors.append(f"{label}: source_in must be < source_out.")
                length = src_out - src_in
                if length < MIN_CLIP_SECONDS:
                    errors.append(
                        f"{label}: source span {length:.3f}s under minimum "
                        f"{MIN_CLIP_SECONDS}s."
                    )
                try:
                    path = resolve_source(clip["source"])
                    dur = video_duration_fn(path)
                    if src_out > dur + 0.02:
                        errors.append(
                            f"{label}: source_out {src_out:.3f}s exceeds file "
                            f"duration {dur:.3f}s."
                        )
                except FileNotFoundError:
                    errors.append(f"{label}: source not found: {clip['source']}")
                except RuntimeError as e:
                    errors.append(f"{label}: {e}")

        elif ttype == "caption":
            if not clip.get("text"):
                errors.append(f"{label}: caption clip needs 'text'.")
            if "source_in" in clip and "source_out" in clip:
                try:
                    if float(clip["source_in"]) >= float(clip["source_out"]):
                        errors.append(f"{label}: source_in must be < source_out.")
                except (TypeError, ValueError):
                    errors.append(f"{label}: invalid source_in/source_out.")

        try:
            start = float(clip["timeline_start"])
            dur = clip_timeline_duration(clip, ttype or "video")
            intervals.append((start, start + dur, label))
        except (KeyError, TypeError, ValueError):
            pass

    intervals.sort(key=lambda x: x[0])
    for j in range(len(intervals) - 1):
        a0, a1, la = intervals[j]
        b0, b1, lb = intervals[j + 1]
        if b0 < a1 - 0.001:
            errors.append(
                f"{la} overlaps {lb} (ends {a1:.3f}s, next starts {b0:.3f}s)."
            )

    return errors


def validate_v2_data(
    data: dict,
    max_length: float | None,
    resolve_source,
    video_duration_fn,
) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_V2:
        errors.append("schema_version must be 2.")
    tracks = data.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("v2 plan needs a non-empty 'tracks' array.")
        return errors

    has_video = False
    for track in tracks:
        ttype = track.get("type")
        if ttype not in TRACK_TYPES:
            errors.append(f"Unknown track type: {ttype!r}.")
            continue
        if ttype == "video" and (track.get("clips") or []):
            has_video = True
        errors.extend(validate_v2_clips_on_track(track, resolve_source, video_duration_fn))

    if not has_video:
        errors.append("v2 plan needs at least one clip on a video track.")

    total = v2_timeline_duration(data)
    if max_length is not None and total > max_length + 0.05:
        errors.append(
            f"Timeline duration {total:.2f}s exceeds max {max_length:.2f}s."
        )

    return errors
