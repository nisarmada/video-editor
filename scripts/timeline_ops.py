"""
Pure edit operations on schema v2 timelines (no file I/O).
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any

from timeline_format import MIN_CLIP_SECONDS, clip_timeline_duration

EPS = 0.001

from media import clip_metadata as _clip_metadata_probe

TimelineOpResult = dict[str, Any]

ALLOWED_CLIP_PROPERTIES = frozenset(
    {
        "zoom",
        "speed",
        "volume",
        "text",
        "caption",
        "group_id",
        "created_by",
        "style_override",
        "audio_source",
    }
)


def _clone(timeline: dict) -> dict:
    return copy.deepcopy(timeline)


def _find_track(timeline: dict, track_id: str) -> dict:
    for track in timeline.get("tracks") or []:
        if track.get("id") == track_id:
            return track
    raise ValueError(f"Track not found: {track_id!r}.")


def _first_video_track(timeline: dict) -> dict | None:
    for tr in timeline.get("tracks") or []:
        if tr.get("type") == "video":
            return tr
    return None


def _insert_video_track(timeline: dict, track: dict) -> int:
    """Place a new video track before the first non-video track (or at end). Returns index."""
    tracks = timeline.setdefault("tracks", [])
    for i, tr in enumerate(tracks):
        if tr.get("type") != "video":
            tracks.insert(i, track)
            return i
    tracks.append(track)
    return len(tracks) - 1


def remove_track(timeline: dict, *, track_id: str) -> TimelineOpResult:
    """Remove a track by id (used as undo for add_clip when the track was auto-created)."""
    tl = _clone(timeline)
    tracks = list(tl.get("tracks") or [])
    idx: int | None = None
    for i, tr in enumerate(tracks):
        if tr.get("id") == track_id:
            idx = i
            break
    if idx is None:
        raise ValueError(f"remove_track: track not found: {track_id!r}.")
    snap = copy.deepcopy(tracks[idx])
    tracks.pop(idx)
    tl["tracks"] = tracks
    return {
        "timeline": tl,
        "undo": {"op": "restore_track", "track": snap, "insert_index": idx},
    }


def restore_track(
    timeline: dict, *, track: dict, insert_index: int
) -> TimelineOpResult:
    """Re-insert a track snapshot (inverse of remove_track)."""
    tl = _clone(timeline)
    tracks = list(tl.get("tracks") or [])
    ti = int(insert_index)
    ti = max(0, min(ti, len(tracks)))
    tracks.insert(ti, copy.deepcopy(track))
    tl["tracks"] = tracks
    return {
        "timeline": tl,
        "undo": {"op": "remove_track", "track_id": track["id"]},
    }


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


def _clip_linking_enabled(timeline: dict) -> bool:
    s = timeline.get("settings")
    if not isinstance(s, dict):
        return True
    v = s.get("clip_linking_enabled")
    return True if v is None else bool(v)


def _expand_linked_clip_ids(timeline: dict, clip_id: str) -> list[str]:
    if not _clip_linking_enabled(timeline):
        return [clip_id]
    try:
        _track, clip, _i = _find_clip(timeline, clip_id)
    except ValueError:
        return [clip_id]
    gid = clip.get("group_id")
    if not isinstance(gid, str) or not gid.strip():
        return [clip_id]
    out: list[str] = []
    for tr in timeline.get("tracks") or []:
        if tr.get("type") not in ("video", "audio"):
            continue
        for c in tr.get("clips") or []:
            if c.get("group_id") == gid and c.get("id"):
                cid = str(c["id"])
                if cid not in out:
                    out.append(cid)
    return out if len(out) > 1 else [clip_id]


def _source_path_for_probe(raw: str) -> Path:
    p = Path(raw)
    if p.is_file():
        return p.resolve()
    return (Path.cwd() / raw).resolve()


def _source_has_audio(raw: str) -> bool:
    p = _source_path_for_probe(raw)
    if not p.is_file():
        return False
    try:
        _d, has_audio, _rot = _clip_metadata_probe(p)
        return bool(has_audio)
    except (OSError, RuntimeError):
        return False


def _intervals_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return b0 < a1 - EPS and a0 < b1 - EPS


def _find_or_create_audio_track(timeline: dict, span_t0: float, span_t1: float) -> dict:
    """Audio track with no clip overlapping [span_t0, span_t1); create one if needed."""
    audio_tracks = [t for t in timeline.get("tracks") or [] if t.get("type") == "audio"]
    audio_tracks.sort(key=lambda t: str(t.get("id", "")))

    for tr in audio_tracks:
        blocked = False
        for c in tr.get("clips") or []:
            c0 = float(c["timeline_start"])
            c1 = _clip_end(c, "audio")
            if _intervals_overlap(span_t0, span_t1, c0, c1):
                blocked = True
                break
        if not blocked:
            return tr

    n = len(audio_tracks) + 1
    new_tr = {
        "id": f"track-audio-{n}",
        "type": "audio",
        "label": f"Audio {n}",
        "clips": [],
    }
    timeline.setdefault("tracks", []).append(new_tr)
    return new_tr


def _linked_partner_id(timeline: dict, clip_id: str) -> str | None:
    if not _clip_linking_enabled(timeline):
        return None
    try:
        tr, clip, _i = _find_clip(timeline, clip_id)
    except ValueError:
        return None
    gid = clip.get("group_id")
    if not isinstance(gid, str) or not gid.strip():
        return None
    ttype = _track_type(tr)
    want = "audio" if ttype == "video" else "video"
    for ot in timeline.get("tracks") or []:
        if ot.get("type") != want:
            continue
        for c in ot.get("clips") or []:
            if c.get("group_id") == gid and c.get("id") and str(c["id"]) != clip_id:
                return str(c["id"])
    return None


def _delete_clips_by_ids(timeline: dict, clip_ids: list[str]) -> list[tuple[str, dict]]:
    """Remove clips; return (track_id, snapshot) for each removed, in arbitrary order."""
    rm = set(clip_ids)
    snapshots: list[tuple[str, dict]] = []
    for tr in timeline.get("tracks") or []:
        clips = list(tr.get("clips") or [])
        kept: list[dict] = []
        for c in clips:
            cid = c.get("id")
            if cid and str(cid) in rm:
                snapshots.append((str(tr["id"]), copy.deepcopy(c)))
            else:
                kept.append(c)
        tr["clips"] = kept
    return snapshots


def split_clip(
    timeline: dict, *, clip_id: str, at_timeline_time: float
) -> TimelineOpResult:
    tl = _clone(timeline)
    if not _clip_linking_enabled(tl):
        return _split_clip_one(tl, clip_id=clip_id, at_timeline_time=at_timeline_time)

    ids = _expand_linked_clip_ids(tl, clip_id)
    if len(ids) <= 1:
        return _split_clip_one(tl, clip_id=clip_id, at_timeline_time=at_timeline_time)

    merge_undos: list[dict[str, Any]] = []
    for cid in sorted(
        ids,
        key=lambda c: (
            0 if _track_type(_find_clip(tl, c)[0]) == "video" else 1,
            c,
        ),
    ):
        tr, cl, _i = _find_clip(tl, cid)
        ttype = _track_type(tr)
        t0 = float(cl["timeline_start"])
        t1 = _clip_end(cl, ttype)
        if at_timeline_time <= t0 + EPS or at_timeline_time >= t1 - EPS:
            raise ValueError(
                f"Split time must be inside every linked clip; "
                f"clip {cid!r} spans ({t0:.3f}s, {t1:.3f}s)."
            )
        one = _split_clip_one(tl, clip_id=cid, at_timeline_time=at_timeline_time)
        merge_undos.append(one["undo"])

    g_left = str(uuid.uuid4())
    g_right = str(uuid.uuid4())
    for step in merge_undos:
        assert step.get("op") == "merge_clips"
        _, left_c, _ = _find_clip(tl, str(step["clip_id_a"]))
        _, right_c, _ = _find_clip(tl, str(step["clip_id_b"]))
        left_c["group_id"] = g_left
        right_c["group_id"] = g_right

    return {
        "timeline": tl,
        "undo": {"op": "sequence", "steps": list(reversed(merge_undos))},
    }


def _split_clip_one(
    tl: dict, *, clip_id: str, at_timeline_time: float
) -> TimelineOpResult:
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


def _trim_clip_one(
    tl: dict,
    *,
    clip_id: str,
    source_in: float | None,
    source_out: float | None,
) -> TimelineOpResult:
    track, clip, _idx = _find_clip(tl, clip_id)
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
    return {
        "timeline": tl,
        "undo": {"op": "trim_clip", "clip_id": clip_id, **undo_props},
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
    ids = (
        _expand_linked_clip_ids(tl, clip_id)
        if _clip_linking_enabled(tl)
        else [clip_id]
    )
    if len(ids) <= 1:
        return _trim_clip_one(
            tl, clip_id=clip_id, source_in=source_in, source_out=source_out
        )

    undo_steps: list[dict[str, Any]] = []
    for cid in sorted(
        ids,
        key=lambda c: (
            0 if _track_type(_find_clip(tl, c)[0]) == "video" else 1,
            c,
        ),
    ):
        one = _trim_clip_one(
            tl, clip_id=cid, source_in=source_in, source_out=source_out
        )
        undo_steps.append(one["undo"])
    return {
        "timeline": tl,
        "undo": {"op": "sequence", "steps": list(reversed(undo_steps))},
    }


def _trim_timeline_edge_one(
    tl: dict,
    *,
    clip_id: str,
    edge: str,
    at_timeline_time: float,
) -> TimelineOpResult:
    """Move clip start/end on the timeline wall clock and keep source trim in sync."""
    track, clip, _idx = _find_clip(tl, clip_id)
    ttype = _track_type(track)
    t0 = float(clip["timeline_start"])
    t1 = _clip_end(clip, ttype)
    at = float(at_timeline_time)
    if edge == "start":
        if at <= t0 + EPS or at >= t1 - EPS:
            raise ValueError(
                f"trim_timeline_edge (start): time must be strictly inside "
                f"({t0:.3f}s, {t1:.3f}s), got {at:.3f}s."
            )
        old_t0 = t0
        old_si = float(clip["source_in"])
        new_si = _source_split_time(clip, at)
        clip["timeline_start"] = at
        clip["source_in"] = new_si
        _check_min_source_span(clip, "Trim start (timeline)")
        _assert_no_overlaps(track)
        return {
            "timeline": tl,
            "undo": {
                "op": "trim_timeline_edge",
                "clip_id": clip_id,
                "edge": "start",
                "old_timeline_start": old_t0,
                "old_source_in": old_si,
                "at_timeline_time": at,
            },
        }
    if edge == "end":
        if at <= t0 + EPS or at >= t1 - EPS:
            raise ValueError(
                f"trim_timeline_edge (end): time must be strictly inside "
                f"({t0:.3f}s, {t1:.3f}s), got {at:.3f}s."
            )
        old_so = float(clip["source_out"])
        new_so = _source_split_time(clip, at)
        clip["source_out"] = new_so
        _check_min_source_span(clip, "Trim end (timeline)")
        _assert_no_overlaps(track)
        return {
            "timeline": tl,
            "undo": {
                "op": "trim_timeline_edge",
                "clip_id": clip_id,
                "edge": "end",
                "old_source_out": old_so,
                "at_timeline_time": at,
            },
        }
    raise ValueError("trim_timeline_edge: edge must be 'start' or 'end'.")


def trim_timeline_edge(
    timeline: dict,
    *,
    clip_id: str,
    edge: str,
    at_timeline_time: float,
) -> TimelineOpResult:
    """Trim clip start/end so the timeline boundary lands at `at_timeline_time`."""
    tl = _clone(timeline)
    e = str(edge)
    if e not in ("start", "end"):
        raise ValueError("trim_timeline_edge: edge must be 'start' or 'end'.")

    if not _clip_linking_enabled(tl):
        return _trim_timeline_edge_one(
            tl, clip_id=clip_id, edge=e, at_timeline_time=at_timeline_time
        )

    ids = _expand_linked_clip_ids(tl, clip_id)
    if len(ids) <= 1:
        return _trim_timeline_edge_one(
            tl, clip_id=clip_id, edge=e, at_timeline_time=at_timeline_time
        )

    merge_undos: list[dict[str, Any]] = []
    for cid in sorted(
        ids,
        key=lambda c: (
            0 if _track_type(_find_clip(tl, c)[0]) == "video" else 1,
            c,
        ),
    ):
        one = _trim_timeline_edge_one(
            tl, clip_id=cid, edge=e, at_timeline_time=at_timeline_time
        )
        merge_undos.append(one["undo"])
    return {
        "timeline": tl,
        "undo": {"op": "sequence", "steps": list(reversed(merge_undos))},
    }


def _move_clip_one(
    tl: dict,
    *,
    clip_id: str,
    timeline_start: float | None,
    track_id: str | None,
) -> TimelineOpResult:
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
        _assert_no_overlaps(src_track)
    else:
        _assert_no_overlaps(src_track)

    return {
        "timeline": tl,
        "undo": {
            "op": "move_clip",
            "clip_id": clip_id,
            "timeline_start": old_start,
            "track_id": old_track_id,
            "skip_link_expand": True,
        },
    }


def move_clip(
    timeline: dict,
    *,
    clip_id: str,
    timeline_start: float | None = None,
    track_id: str | None = None,
    skip_link_expand: bool = False,
) -> TimelineOpResult:
    if timeline_start is None and track_id is None:
        raise ValueError("move_clip requires timeline_start and/or track_id.")

    tl = _clone(timeline)
    if skip_link_expand:
        return _move_clip_one(
            tl, clip_id=clip_id, timeline_start=timeline_start, track_id=track_id
        )

    partner = _linked_partner_id(tl, clip_id)
    if (
        partner
        and _clip_linking_enabled(tl)
        and timeline_start is not None
        and track_id is None
    ):
        src_track, clip, _i = _find_clip(tl, clip_id)
        old_start = float(clip["timeline_start"])
        delta = float(timeline_start) - old_start
        ids = sorted([clip_id, partner], key=lambda x: (_track_type(_find_clip(tl, x)[0]) != "video", x))
        undo_steps: list[dict[str, Any]] = []
        for cid in ids:
            tr, cl, _j = _find_clip(tl, cid)
            new_t = float(cl["timeline_start"]) + delta
            one = _move_clip_one(
                tl,
                clip_id=cid,
                timeline_start=new_t,
                track_id=None,
            )
            undo_steps.append(one["undo"])
        return {
            "timeline": tl,
            "undo": {"op": "sequence", "steps": list(reversed(undo_steps))},
        }

    return _move_clip_one(
        tl, clip_id=clip_id, timeline_start=timeline_start, track_id=track_id
    )


def _delete_clip_one(tl: dict, *, clip_id: str) -> None:
    track, clip, idx = _find_clip(tl, clip_id)
    clips = list(track.get("clips") or [])
    clips.pop(idx)
    track["clips"] = clips


def delete_clip_solo(timeline: dict, *, clip_id: str) -> TimelineOpResult:
    """Remove one clip by id — no linked-group expansion (for compound undos)."""
    tl = _clone(timeline)
    track, clip, idx = _find_clip(tl, clip_id)
    snap = copy.deepcopy(clip)
    tid = str(track["id"])
    clips = list(track.get("clips") or [])
    clips.pop(idx)
    track["clips"] = clips
    return {
        "timeline": tl,
        "undo": {"op": "add_clip", "track_id": tid, "clip": snap},
    }


def delete_clip(timeline: dict, *, clip_id: str) -> TimelineOpResult:
    tl = _clone(timeline)
    ids = (
        _expand_linked_clip_ids(tl, clip_id)
        if _clip_linking_enabled(tl)
        else [clip_id]
    )
    snapshots: list[tuple[str, dict]] = []
    for cid in ids:
        track, clip, idx = _find_clip(tl, cid)
        snapshots.append((str(track["id"]), copy.deepcopy(clip)))
        _delete_clip_one(tl, clip_id=cid)

    if len(snapshots) == 1:
        tid, snap = snapshots[0]
        return {
            "timeline": tl,
            "undo": {"op": "add_clip", "track_id": tid, "clip": snap},
        }

    steps = [{"op": "add_clip", "track_id": tid, "clip": snap} for tid, snap in snapshots]
    return {
        "timeline": tl,
        "undo": {"op": "sequence", "steps": list(reversed(steps))},
    }


def add_clip(
    timeline: dict,
    *,
    track_id: str | None = None,
    clip: dict,
) -> TimelineOpResult:
    if not clip.get("id"):
        raise ValueError("add_clip: clip must include 'id'.")
    for field in ("timeline_start", "created_by"):
        if field not in clip:
            raise ValueError(f"add_clip: clip missing '{field}'.")

    tl = _clone(timeline)
    created_empty_track = False
    if track_id is not None:
        track = _find_track(tl, track_id)
    else:
        existing = _first_video_track(tl)
        if existing is not None:
            track = existing
        else:
            tid = f"track-video-{uuid.uuid4().hex[:12]}"
            track = {
                "id": tid,
                "type": "video",
                "label": "Video",
                "clips": [],
            }
            _insert_video_track(tl, track)
            created_empty_track = True

    ttype = _track_type(track)
    new_clip = copy.deepcopy(clip)
    if ttype in ("video", "audio"):
        for field in ("source", "source_in", "source_out"):
            if field not in new_clip:
                raise ValueError(f"add_clip: video/audio clip missing '{field}'.")
        _check_min_source_span(new_clip, "New clip")

    track.setdefault("clips", []).append(new_clip)
    _assert_no_overlaps(track)

    if created_empty_track:
        return {
            "timeline": tl,
            "undo": {"op": "remove_track", "track_id": track["id"]},
        }
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
    if left.get("audio_source") == "detached" or right.get("audio_source") == "detached":
        merged["audio_source"] = "detached"
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


def set_timeline_settings(
    timeline: dict, *, properties: dict[str, Any]
) -> TimelineOpResult:
    if not properties:
        raise ValueError("set_timeline_settings: properties must be non-empty.")
    tl = _clone(timeline)
    settings = tl.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        tl["settings"] = settings
    previous: dict[str, Any] = {}
    for key, value in properties.items():
        if key in settings:
            previous[key] = copy.deepcopy(settings[key])
        else:
            previous[key] = None
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = copy.deepcopy(value)
    return {
        "timeline": tl,
        "undo": {
            "op": "set_timeline_settings",
            "properties": previous,
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
    propagate_speed_vol = _clip_linking_enabled(tl) and (
        "speed" in properties or "volume" in properties
    )
    if propagate_speed_vol:
        pid = _linked_partner_id(tl, clip_id)
        if pid:
            undo_steps: list[dict[str, Any]] = []
            one = _set_clip_property_one(tl, clip_id=clip_id, properties=properties)
            undo_steps.append(one["undo"])
            partner_props = {
                k: properties[k] for k in ("speed", "volume") if k in properties
            }
            two = _set_clip_property_one(tl, clip_id=pid, properties=partner_props)
            undo_steps.append(two["undo"])
            return {
                "timeline": tl,
                "undo": {"op": "sequence", "steps": list(reversed(undo_steps))},
            }

    return _set_clip_property_one(tl, clip_id=clip_id, properties=properties)


def _set_clip_property_one(
    tl: dict, *, clip_id: str, properties: dict[str, Any]
) -> TimelineOpResult:
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


def set_track_property(
    timeline: dict, *, track_id: str, properties: dict[str, Any]
) -> TimelineOpResult:
    if not properties:
        raise ValueError("set_track_property: properties must be non-empty.")
    if set(properties.keys()) - {"muted", "volume", "locked"}:
        raise ValueError(
            "set_track_property: only 'muted', 'volume', and 'locked' are supported."
        )

    tl = _clone(timeline)
    track = _find_track(tl, track_id)
    tt = _track_type(track)
    if tt not in ("video", "audio"):
        raise ValueError("set_track_property: track must be video or audio.")

    previous: dict[str, Any] = {}
    for key, value in properties.items():
        if key in track:
            previous[key] = copy.deepcopy(track[key])
        else:
            previous[key] = None
        if value is None:
            track.pop(key, None)
        elif key == "muted":
            track[key] = bool(value)
        elif key == "volume":
            track[key] = float(value)
        elif key == "locked":
            track[key] = bool(value)
        else:
            track[key] = copy.deepcopy(value)

    return {
        "timeline": tl,
        "undo": {
            "op": "set_track_property",
            "track_id": track_id,
            "properties": previous,
        },
    }


def separate_audio(timeline: dict, *, clip_id: str) -> TimelineOpResult:
    tl = _clone(timeline)
    track, clip, _idx = _find_clip(tl, clip_id)
    if _track_type(track) != "video":
        raise ValueError("separate_audio: clip must be on a video track.")
    if clip.get("audio_source") == "detached":
        raise ValueError("Audio is already separated for this clip.")

    src = str(clip.get("source") or "")
    if not src:
        raise ValueError("separate_audio: video clip has no source.")
    if not _source_has_audio(src):
        raise ValueError(
            "separate_audio: this source has no audio stream to separate."
        )

    prev_group = clip.get("group_id")
    prev_audio_src = clip.get("audio_source")
    gid = (
        str(prev_group).strip()
        if isinstance(prev_group, str) and str(prev_group).strip()
        else str(uuid.uuid4())
    )

    t0 = float(clip["timeline_start"])
    t1 = _clip_end(clip, "video")
    audio_track = _find_or_create_audio_track(tl, t0, t1)

    new_id = str(uuid.uuid4())
    aud = {
        "id": new_id,
        "source": src,
        "source_in": float(clip["source_in"]),
        "source_out": float(clip["source_out"]),
        "timeline_start": t0,
        "created_by": "user",
        "group_id": gid,
        "speed": float(clip.get("speed") or 1.0) or 1.0,
        "volume": float(clip.get("volume") if clip.get("volume") is not None else 1.0),
    }
    clip["group_id"] = gid
    clip["audio_source"] = "detached"
    audio_track.setdefault("clips", []).append(aud)
    _assert_no_overlaps(audio_track)

    restore_props: dict[str, Any] = {
        "group_id": copy.deepcopy(prev_group) if prev_group is not None else None,
        "audio_source": copy.deepcopy(prev_audio_src)
        if prev_audio_src is not None
        else None,
    }

    return {
        "timeline": tl,
        "undo": {
            "op": "sequence",
            "steps": [
                {"op": "delete_clip_solo", "clip_id": new_id},
                {
                    "op": "set_clip_property",
                    "clip_id": clip_id,
                    "properties": restore_props,
                },
            ],
        },
    }


def reattach_audio(timeline: dict, *, clip_id: str) -> TimelineOpResult:
    tl = _clone(timeline)
    tr, clip, _idx = _find_clip(tl, clip_id)
    ttype = _track_type(tr)

    audio_id: str | None = None
    video_id: str | None = None

    if ttype == "video":
        video_id = str(clip["id"])
        if clip.get("audio_source") != "detached":
            raise ValueError("reattach_audio: video clip is not in detached audio mode.")
        gid = clip.get("group_id")
        if not isinstance(gid, str) or not gid.strip():
            raise ValueError("reattach_audio: missing group_id on video clip.")
        for atr in tl.get("tracks") or []:
            if atr.get("type") != "audio":
                continue
            for c in atr.get("clips") or []:
                if c.get("group_id") == gid and c.get("id"):
                    audio_id = str(c["id"])
                    break
            if audio_id:
                break
        if not audio_id:
            raise ValueError("reattach_audio: no matching audio clip found.")
    elif ttype == "audio":
        audio_id = str(clip["id"])
        gid = clip.get("group_id")
        if not isinstance(gid, str) or not gid.strip():
            raise ValueError("reattach_audio: audio clip has no group_id.")
        for vtr in tl.get("tracks") or []:
            if vtr.get("type") != "video":
                continue
            for c in vtr.get("clips") or []:
                if c.get("group_id") == gid and c.get("audio_source") == "detached":
                    video_id = str(c["id"])
                    break
            if video_id:
                break
        if not video_id:
            raise ValueError("reattach_audio: no matching detached video clip found.")
    else:
        raise ValueError("reattach_audio: clip must be video or audio.")

    assert video_id and audio_id
    atr, aud_cl, _ai = _find_clip(tl, audio_id)
    aud_snap = copy.deepcopy(aud_cl)
    _vtr, vid_cl, _vi = _find_clip(tl, video_id)
    prev_vid_group = vid_cl.get("group_id")
    audio_track_id = str(atr["id"])

    _delete_clip_one(tl, clip_id=audio_id)

    vid_cl["audio_source"] = "embedded"
    # Keep group_id so re-separate can find pairing; user can unlink explicitly.

    return {
        "timeline": tl,
        "undo": {
            "op": "sequence",
            "steps": [
                {
                    "op": "set_clip_property",
                    "clip_id": video_id,
                    "properties": {
                        "audio_source": "detached",
                        "group_id": copy.deepcopy(prev_vid_group),
                    },
                },
                {"op": "add_clip", "track_id": audio_track_id, "clip": aud_snap},
            ],
        },
    }


def unlink_clips(timeline: dict, *, clip_id: str) -> TimelineOpResult:
    tl = _clone(timeline)
    pid = _linked_partner_id(tl, clip_id)
    if not pid:
        raise ValueError("unlink_clips: clip has no linked partner (group_id).")

    props_a: dict[str, Any] = {"group_id": None}
    props_b: dict[str, Any] = {"group_id": None}
    one = _set_clip_property_one(tl, clip_id=clip_id, properties=props_a)
    two = _set_clip_property_one(tl, clip_id=pid, properties=props_b)
    return {
        "timeline": tl,
        "undo": {
            "op": "sequence",
            "steps": list(reversed([two["undo"], one["undo"]])),
        },
    }


def replace_timeline(timeline: dict, *, timeline_data: dict) -> TimelineOpResult:
    """Swap the entire v2 timeline (e.g. AI planner output); undo restores the previous tree."""
    old_snap = copy.deepcopy(timeline)
    new_tl = copy.deepcopy(timeline_data)
    return {
        "timeline": new_tl,
        "undo": {"op": "replace_timeline", "previous_timeline": old_snap},
    }


def apply_undo(timeline: dict, undo: dict) -> TimelineOpResult:
    """Apply an undo payload returned by any operation."""
    op = undo.get("op")
    if op == "sequence":
        tl2 = copy.deepcopy(timeline)
        redo_steps: list[dict[str, Any]] = []
        for step in undo.get("steps") or []:
            r = apply_undo(tl2, step)
            tl2 = r["timeline"]
            redo_steps.insert(0, r["undo"])
        return {"timeline": tl2, "undo": {"op": "sequence", "steps": redo_steps}}
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
        tl3 = _clone(timeline)
        kwargs: dict[str, Any] = {"clip_id": undo["clip_id"]}
        if "source_in" in undo:
            kwargs["source_in"] = undo["source_in"]
        if "source_out" in undo:
            kwargs["source_out"] = undo["source_out"]
        return _trim_clip_one(
            tl3,
            clip_id=str(undo["clip_id"]),
            source_in=kwargs.get("source_in"),
            source_out=kwargs.get("source_out"),
        )
    if op == "trim_timeline_edge":
        cid = str(undo["clip_id"])
        edge = str(undo.get("edge") or "")
        if "old_timeline_start" in undo or "old_source_out" in undo:
            tl4 = _clone(timeline)
            tr, clip, _i = _find_clip(tl4, cid)
            at_applied = float(undo["at_timeline_time"])
            if edge == "start":
                clip["timeline_start"] = float(undo["old_timeline_start"])
                clip["source_in"] = float(undo["old_source_in"])
            elif edge == "end":
                clip["source_out"] = float(undo["old_source_out"])
            else:
                raise ValueError(f"trim_timeline_edge undo: bad edge {edge!r}.")
            _assert_no_overlaps(tr)
            return {
                "timeline": tl4,
                "undo": {
                    "op": "trim_timeline_edge",
                    "clip_id": cid,
                    "edge": edge,
                    "at_timeline_time": at_applied,
                },
            }
        return trim_timeline_edge(
            timeline,
            clip_id=cid,
            edge=edge,
            at_timeline_time=float(undo["at_timeline_time"]),
        )
    if op == "move_clip":
        return move_clip(
            timeline,
            clip_id=undo["clip_id"],
            timeline_start=undo.get("timeline_start"),
            track_id=undo.get("track_id"),
            skip_link_expand=bool(undo.get("skip_link_expand")),
        )
    if op == "delete_clip":
        return delete_clip(timeline, clip_id=undo["clip_id"])
    if op == "delete_clip_solo":
        return delete_clip_solo(timeline, clip_id=undo["clip_id"])
    if op == "add_clip":
        tid = undo.get("track_id")
        return add_clip(timeline, track_id=tid, clip=undo["clip"])
    if op == "remove_track":
        return remove_track(timeline, track_id=str(undo["track_id"]))
    if op == "restore_track":
        return restore_track(
            timeline,
            track=undo["track"],
            insert_index=int(undo["insert_index"]),
        )
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
    if op == "set_timeline_settings":
        tl = _clone(timeline)
        settings = tl.setdefault("settings", {})
        if not isinstance(settings, dict):
            tl["settings"] = {}
            settings = tl["settings"]
        redo: dict[str, Any] = {}
        for key in undo["properties"]:
            redo[key] = copy.deepcopy(settings[key]) if key in settings else None
        for key, value in undo["properties"].items():
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = copy.deepcopy(value)
        return {
            "timeline": tl,
            "undo": {"op": "set_timeline_settings", "properties": redo},
        }
    if op == "set_track_property":
        tl = _clone(timeline)
        tr = _find_track(tl, str(undo["track_id"]))
        redo: dict[str, Any] = {}
        for key in undo["properties"]:
            redo[key] = copy.deepcopy(tr[key]) if key in tr else None
        for key, value in undo["properties"].items():
            if value is None:
                tr.pop(key, None)
            else:
                tr[key] = copy.deepcopy(value)
        return {
            "timeline": tl,
            "undo": {
                "op": "set_track_property",
                "track_id": undo["track_id"],
                "properties": redo,
            },
        }
    if op == "replace_timeline":
        prev = undo.get("previous_timeline")
        if not isinstance(prev, dict):
            raise ValueError("replace_timeline undo: missing previous_timeline.")
        cur_snap = copy.deepcopy(timeline)
        return {
            "timeline": copy.deepcopy(prev),
            "undo": {"op": "replace_timeline", "previous_timeline": cur_snap},
        }
    raise ValueError(f"Unknown undo op: {op!r}.")


def apply_undo_op(timeline: dict, undo: dict) -> TimelineOpResult:
    """Apply an inverse payload from the undo stack (same shape as `apply_undo` in tests)."""
    return apply_undo(timeline, undo)


OPERATIONS = {
    "split_clip": split_clip,
    "trim_clip": trim_clip,
    "trim_timeline_edge": trim_timeline_edge,
    "move_clip": move_clip,
    "delete_clip": delete_clip,
    "delete_clip_solo": delete_clip_solo,
    "add_clip": add_clip,
    "remove_track": remove_track,
    "restore_track": restore_track,
    "merge_clips": merge_clips,
    "replace_timeline": replace_timeline,
    "set_clip_property": set_clip_property,
    "set_track_property": set_track_property,
    "set_timeline_settings": set_timeline_settings,
    "separate_audio": separate_audio,
    "reattach_audio": reattach_audio,
    "unlink_clips": unlink_clips,
    "apply_undo": apply_undo_op,
}


def dispatch_operation(
    timeline: dict,
    operation: str,
    arguments: dict[str, Any] | None = None,
) -> TimelineOpResult:
    """Run a named timeline op (for API / editor)."""
    fn = OPERATIONS.get(operation)
    if fn is None:
        known = ", ".join(sorted(OPERATIONS))
        raise ValueError(f"Unknown operation {operation!r}. Known: {known}.")
    return fn(timeline, **(arguments or {}))


def batch_operations(timeline: dict, *, steps: list[dict[str, Any]]) -> TimelineOpResult:
    """Run multiple ops in one request; single undo step (sequence) for one undo pop."""
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError("batch_operations: non-empty steps list required.")
    cur = timeline
    undo_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("batch_operations: each step must be an object.")
        op = step.get("operation")
        args = step.get("arguments")
        if not isinstance(op, str) or not op:
            raise ValueError("batch_operations: step missing operation string.")
        if args is not None and not isinstance(args, dict):
            raise ValueError("batch_operations: step.arguments must be an object.")
        result = dispatch_operation(cur, op, args if isinstance(args, dict) else {})
        cur = result["timeline"]
        undo_steps.append(result["undo"])
    return {
        "timeline": cur,
        "undo": {"op": "sequence", "steps": list(reversed(undo_steps))},
    }


OPERATIONS["batch_operations"] = batch_operations
