"""
Pure edit operations on schema v2 timelines (no file I/O).
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from timeline_format import MIN_CLIP_SECONDS, clip_timeline_duration

EPS = 0.001

TimelineOpResult = dict[str, Any]

ALLOWED_CLIP_PROPERTIES = frozenset(
    {"zoom", "speed", "volume", "text", "caption", "group_id", "created_by"}
)


def _clone(timeline: dict) -> dict:
    return copy.deepcopy(timeline)


def _find_track(timeline: dict, track_id: str) -> dict:
    for track in timeline.get("tracks") or []:
        if track.get("id") == track_id:
            return track
    raise ValueError(f"Track not found: {track_id!r}.")


def _find_clip(
    timeline: dict, clip_id: str
) -> tuple[dict, dict, int]:
    """Return (track, clip, clip_index)."""
    for track in timeline.get("tracks") or []:
        clips = track.get("clips") or []
        for i, clip in enumerate(clips):
            if clip.get("id") == clip_id:
                return track, clip, i
    raise ValueError(f"Clip not found: {clip_id!r}.")


def _track_type(track: dict) -> str:
    return track.get("type") or "video"


def _clip_end(clip: dict, track_type: str) -> float:
    start = float(clip["timeline_start"])
    return start + clip_timeline_duration(clip, track_type)


def _check_min_source_span(clip: dict, label: str) -> None:
    if "source_in" not in clip or "source_out" not in clip:
        return
    span = float(clip["source_out"]) - float(clip["source_in"])
    if span + 1e-9 < MIN_CLIP_SECONDS:
        raise ValueError(
            f"{label}: source span {span:.3f}s under minimum {MIN_CLIP_SECONDS}s."
        )


def _assert_no_overlaps(track: dict, *, ignore_clip_id: str | None = None) -> None:
    ttype = _track_type(track)
    intervals: list[tuple[float, float, str]] = []
    for clip in track.get("clips") or []:
        if ignore_clip_id and clip.get("id") == ignore_clip_id:
            continue
        start = float(clip["timeline_start"])
        end = _clip_end(clip, ttype)
        intervals.append((start, end, str(clip.get("id"))))
    intervals.sort(key=lambda x: x[0])
    for j in range(len(intervals) - 1):
        a0, a1, la = intervals[j]
        b0, _b1, lb = intervals[j + 1]
        if b0 < a1 - EPS:
            raise ValueError(
                f"Clips overlap on track {track.get('id')!r}: "
                f"{la} ends {a1:.3f}s, {lb} starts {b0:.3f}s."
            )


def _source_split_time(clip: dict, at_timeline_time: float) -> float:
    speed = float(clip.get("speed") or 1.0)
    if speed <= 0:
        speed = 1.0
    t0 = float(clip["timeline_start"])
    src_in = float(clip["source_in"])
    offset = at_timeline_time - t0
    return src_in + offset * speed


def _copy_clip_fields(clip: dict) -> dict:
    """Shallow copy of clip dict for mutation."""
    return dict(clip)


def split_clip(
    timeline: dict, *, clip_id: str, at_timeline_time: float
) -> TimelineOpResult:
    tl = _clone(timeline)
    track, clip, idx = _find_clip(tl, clip_id)
    ttype = _track_type(track)
    t0 = float(clip["timeline_start"])
    t1 = _clip_end(clip, ttype)
    if at_timeline_time <= t0 + EPS or at_timeline_time >= t1 - EPS:
        raise ValueError(
            f"Split time {at_timeline_time:.3f}s must be strictly inside "
            f"clip timeline span ({t0:.3f}s, {t1:.3f}s)."
        )

    src_split = _source_split_time(clip, at_timeline_time)
    src_in = float(clip["source_in"])
    src_out = float(clip["source_out"])
    if src_split <= src_in + EPS or src_split >= src_out - EPS:
        raise ValueError("Split maps to invalid source time.")

    left = _copy_clip_fields(clip)
    right = _copy_clip_fields(clip)
    right_id = str(uuid.uuid4())

    left["source_out"] = src_split
    right["id"] = right_id
    right["source_in"] = src_split
    right["timeline_start"] = at_timeline_time

    _check_min_source_span(left, "Left split part")
    _check_min_source_span(right, "Right split part")

    clips = list(track.get("clips") or [])
    clips[idx : idx + 1] = [left, right]
    track["clips"] = clips
    _assert_no_overlaps(track)

    return {
        "timeline": tl,
        "undo": {
            "op": "merge_clips",
            "clip_id_a": left["id"],
            "clip_id_b": right_id,
        },
    }


def trim_clip(
    timeline: dict,
    *,
    clip_id: str,
    source_in: float | None = None,
    source_out: float | None = None,
) -> TimelineOpResult:
    if source_in is None and source_out is None:
        raise ValueError("trim_clip requires source_in and/or source_out.")

    tl = _clone(timeline)
    track, clip, _idx = _find_clip(tl, clip_id)
    ttype = _track_type(track)

    old_in = float(clip["source_in"]) if "source_in" in clip else None
    old_out = float(clip["source_out"]) if "source_out" in clip else None

    undo_props: dict[str, float] = {}
    if source_in is not None:
        undo_props["source_in"] = old_in if old_in is not None else float(clip["source_in"])
        clip["source_in"] = float(source_in)
    if source_out is not None:
        undo_props["source_out"] = old_out if old_out is not None else float(clip["source_out"])
        clip["source_out"] = float(source_out)

    if "source_in" in clip and "source_out" in clip:
        if float(clip["source_in"]) >= float(clip["source_out"]):
            raise ValueError("source_in must be < source_out after trim.")
        _check_min_source_span(clip, "Trimmed clip")

    _assert_no_overlaps(track)
    # Duration shrink cannot create overlaps; explicit check still validates order.

    return {
        "timeline": tl,
        "undo": {"op": "trim_clip", "clip_id": clip_id, **undo_props},
    }


def move_clip(
    timeline: dict,
    *,
    clip_id: str,
    timeline_start: float | None = None,
    track_id: str | None = None,
) -> TimelineOpResult:
    if timeline_start is None and track_id is None:
        raise ValueError("move_clip requires timeline_start and/or track_id.")

    tl = _clone(timeline)
    src_track, clip, idx = _find_clip(tl, clip_id)
    old_start = float(clip["timeline_start"])
    old_track_id = src_track["id"]

    dest_track = src_track
    if track_id is not None and track_id != old_track_id:
        dest_track = _find_track(tl, track_id)
        clips = list(src_track.get("clips") or [])
        clips.pop(idx)
        src_track["clips"] = clips
        dest_track.setdefault("clips", []).append(clip)

    if timeline_start is not None:
        clip["timeline_start"] = float(timeline_start)

    _assert_no_overlaps(dest_track, ignore_clip_id=None)
    if dest_track is not src_track:
        pass
    else:
        _assert_no_overlaps(src_track)

    return {
        "timeline": tl,
        "undo": {
            "op": "move_clip",
            "clip_id": clip_id,
            "timeline_start": old_start,
            "track_id": old_track_id,
        },
    }


def delete_clip(timeline: dict, *, clip_id: str) -> TimelineOpResult:
    tl = _clone(timeline)
    track, clip, idx = _find_clip(tl, clip_id)
    track_id = track["id"]
    snapshot = copy.deepcopy(clip)
    clips = list(track.get("clips") or [])
    clips.pop(idx)
    track["clips"] = clips

    return {
        "timeline": tl,
        "undo": {"op": "add_clip", "track_id": track_id, "clip": snapshot},
    }


def add_clip(timeline: dict, *, track_id: str, clip: dict) -> TimelineOpResult:
    if not clip.get("id"):
        raise ValueError("add_clip: clip must include 'id'.")
    for field in ("timeline_start", "created_by"):
        if field not in clip:
            raise ValueError(f"add_clip: clip missing '{field}'.")

    tl = _clone(timeline)
    track = _find_track(tl, track_id)
    ttype = _track_type(track)
    new_clip = copy.deepcopy(clip)
    if ttype in ("video", "audio"):
        for field in ("source", "source_in", "source_out"):
            if field not in new_clip:
                raise ValueError(f"add_clip: video/audio clip missing '{field}'.")
        _check_min_source_span(new_clip, "New clip")

    track.setdefault("clips", []).append(new_clip)
    _assert_no_overlaps(track)

    return {
        "timeline": tl,
        "undo": {"op": "delete_clip", "clip_id": new_clip["id"]},
    }


def merge_clips(
    timeline: dict, *, clip_id_a: str, clip_id_b: str
) -> TimelineOpResult:
    tl = _clone(timeline)
    track_a, clip_a, _idx_a = _find_clip(tl, clip_id_a)
    track_b, clip_b, _idx_b = _find_clip(tl, clip_id_b)

    if track_a["id"] != track_b["id"]:
        raise ValueError("merge_clips: clips must be on the same track.")
    track = track_a
    ttype = _track_type(track)

    if float(clip_a["timeline_start"]) <= float(clip_b["timeline_start"]):
        left, right = clip_a, clip_b
    else:
        left, right = clip_b, clip_a

    left_end = _clip_end(left, ttype)
    right_start = float(right["timeline_start"])
    if abs(left_end - right_start) > EPS:
        raise ValueError(
            "merge_clips: clips must be adjacent on the timeline "
            f"(left ends {left_end:.3f}s, right starts {right_start:.3f}s)."
        )

    if left.get("source") != right.get("source"):
        raise ValueError("merge_clips: clips must share the same source.")

    if "source_in" in left and "source_out" in right:
        if abs(float(left["source_out"]) - float(right["source_in"])) > EPS:
            raise ValueError(
                "merge_clips: source_out of left clip must match source_in of right."
            )

    boundary_time = left_end
    merged = _copy_clip_fields(left)
    merged["source_out"] = float(right["source_out"])
    if right.get("text") and not merged.get("text"):
        merged["text"] = right["text"]
    if right.get("caption") and not merged.get("caption"):
        merged["caption"] = right["caption"]

    left_id = left["id"]
    right_id = right["id"]
    clips = [
        c
        for c in (track.get("clips") or [])
        if c.get("id") not in (left_id, right_id)
    ]
    clips.append(merged)
    clips.sort(key=lambda c: float(c["timeline_start"]))
    track["clips"] = clips
    _assert_no_overlaps(track)

    return {
        "timeline": tl,
        "undo": {
            "op": "split_clip",
            "clip_id": merged["id"],
            "at_timeline_time": boundary_time,
        },
    }


def set_clip_property(
    timeline: dict, *, clip_id: str, properties: dict[str, Any]
) -> TimelineOpResult:
    if not properties:
        raise ValueError("set_clip_property: properties must be non-empty.")
    bad = set(properties) - ALLOWED_CLIP_PROPERTIES
    if bad:
        raise ValueError(f"set_clip_property: disallowed keys: {sorted(bad)!r}.")

    tl = _clone(timeline)
    _track, clip, _idx = _find_clip(tl, clip_id)

    previous: dict[str, Any] = {}
    for key, value in properties.items():
        if key in clip:
            previous[key] = copy.deepcopy(clip[key])
        else:
            previous[key] = None
        if value is None:
            clip.pop(key, None)
        else:
            clip[key] = copy.deepcopy(value)

    return {
        "timeline": tl,
        "undo": {
            "op": "set_clip_property",
            "clip_id": clip_id,
            "properties": previous,
        },
    }


def apply_undo(timeline: dict, undo: dict) -> TimelineOpResult:
    """Apply an undo payload returned by any operation."""
    op = undo.get("op")
    if op == "split_clip":
        return split_clip(
            timeline,
            clip_id=undo["clip_id"],
            at_timeline_time=float(undo["at_timeline_time"]),
        )
    if op == "merge_clips":
        return merge_clips(
            timeline,
            clip_id_a=undo["clip_id_a"],
            clip_id_b=undo["clip_id_b"],
        )
    if op == "trim_clip":
        kwargs: dict[str, Any] = {"clip_id": undo["clip_id"]}
        if "source_in" in undo:
            kwargs["source_in"] = undo["source_in"]
        if "source_out" in undo:
            kwargs["source_out"] = undo["source_out"]
        return trim_clip(timeline, **kwargs)
    if op == "move_clip":
        return move_clip(
            timeline,
            clip_id=undo["clip_id"],
            timeline_start=undo.get("timeline_start"),
            track_id=undo.get("track_id"),
        )
    if op == "delete_clip":
        return delete_clip(timeline, clip_id=undo["clip_id"])
    if op == "add_clip":
        return add_clip(timeline, track_id=undo["track_id"], clip=undo["clip"])
    if op == "set_clip_property":
        tl = _clone(timeline)
        _, clip, _ = _find_clip(tl, undo["clip_id"])
        redo: dict[str, Any] = {}
        for key in undo["properties"]:
            redo[key] = copy.deepcopy(clip[key]) if key in clip else None
        for key, value in undo["properties"].items():
            if value is None:
                clip.pop(key, None)
            else:
                clip[key] = copy.deepcopy(value)
        return {
            "timeline": tl,
            "undo": {
                "op": "set_clip_property",
                "clip_id": undo["clip_id"],
                "properties": redo,
            },
        }
    raise ValueError(f"Unknown undo op: {op!r}.")
