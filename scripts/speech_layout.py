"""
Deterministic speech timeline layout (EDL → contiguous timeline).

Planner outputs ordered source ranges; refinement adjusts trims; this module
places clips on the timeline and ripples linked video/caption clips.
"""

from __future__ import annotations

import copy
from typing import Any

from timeline_format import clip_timeline_duration, get_track

SPEECH_LAYOUT_EDL = "edl"
SPEECH_LAYOUT_CONTIGUOUS = "contiguous"

GAP_CONTINUOUS = "continuous"
GAP_PAUSE = "pause"

DEFAULT_GAP_AFTER: dict[str, Any] = {"mode": GAP_CONTINUOUS}


def track_uses_speech_layout(track: dict) -> bool:
    return track.get("speech_layout_mode") in (SPEECH_LAYOUT_EDL, SPEECH_LAYOUT_CONTIGUOUS)


def _clip_wall_s(clip: dict) -> float:
    try:
        return clip_timeline_duration(clip, "audio")
    except (TypeError, ValueError, KeyError):
        si = float(clip["source_in"])
        so = float(clip["source_out"])
        speed = float(clip.get("speed") or 1.0)
        return (so - si) / speed


def gap_duration_s(gap_after: Any) -> float:
    if not isinstance(gap_after, dict):
        return 0.0
    mode = gap_after.get("mode", GAP_CONTINUOUS)
    if mode in (GAP_CONTINUOUS, "none", None):
        return 0.0
    if mode == GAP_PAUSE:
        if "duration_s" in gap_after:
            return max(0.0, float(gap_after["duration_s"]))
        if "duration_ms" in gap_after:
            return max(0.0, float(gap_after["duration_ms"]) / 1000.0)
    return 0.0


def normalize_gap_after(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_GAP_AFTER)
    mode = raw.get("mode", GAP_CONTINUOUS)
    if mode == GAP_PAUSE:
        out: dict[str, Any] = {"mode": GAP_PAUSE}
        if "duration_s" in raw:
            out["duration_s"] = max(0.0, float(raw["duration_s"]))
        elif "duration_ms" in raw:
            out["duration_ms"] = max(0.0, float(raw["duration_ms"]))
        else:
            out["duration_s"] = 0.3
        fill = raw.get("fill")
        if fill in ("silence", "room_tone"):
            out["fill"] = fill
        else:
            out["fill"] = "room_tone"
        return out
    return {"mode": GAP_CONTINUOUS}


def ordered_speech_clips(track: dict) -> list[dict]:
    clips = [c for c in track.get("clips") or [] if isinstance(c, dict)]
    if any(c.get("speech_order") is not None for c in clips):
        return sorted(clips, key=lambda c: int(c.get("speech_order", 0)))
    if track.get("speech_layout_mode") == SPEECH_LAYOUT_EDL:
        return clips
    return sorted(clips, key=lambda c: float(c.get("timeline_start", 0)))


def mark_speech_edl_track(track: dict) -> None:
    """Planner EDL: clips in array order, no timeline_start required."""
    track["speech_layout_mode"] = SPEECH_LAYOUT_EDL
    clips = track.get("clips") or []
    for i, clip in enumerate(clips):
        if isinstance(clip, dict):
            clip["speech_order"] = i
            clip.pop("timeline_start", None)
            clip.pop("timeline_end", None)
            if "gap_after" not in clip and i + 1 < len(clips):
                clip["gap_after"] = dict(DEFAULT_GAP_AFTER)


def detect_and_normalize_edl(timeline: dict) -> bool:
    """
    Mark speech EDL tracks and strip model-supplied timeline times on speech.
    Returns True if any track was normalized.
    """
    changed = False
    for tr in timeline.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        clips = tr.get("clips") or []
        if not clips:
            continue
        if tr.get("speech_layout_mode") == SPEECH_LAYOUT_EDL:
            mark_speech_edl_track(tr)
            changed = True
            continue
        missing = [c for c in clips if isinstance(c, dict) and "timeline_start" not in c]
        if missing and len(missing) == len(clips):
            mark_speech_edl_track(tr)
            changed = True
    return changed


def strip_llm_speech_timeline_fields(track: dict) -> None:
    """Remove timeline_start / timeline_end on speech EDL clips (code owns layout)."""
    if track.get("type") != "audio":
        return
    if track.get("speech_layout_mode") != SPEECH_LAYOUT_EDL:
        return
    for clip in track.get("clips") or []:
        if isinstance(clip, dict):
            clip.pop("timeline_start", None)
            clip.pop("timeline_end", None)


def build_speech_layout(
    timeline: dict,
    *,
    track_id: str | None = None,
    anchor_time: float = 0.0,
) -> dict[str, float]:
    """
    Place speech clips back-to-back using each clip's gap_after policy.
    Returns map clip_id -> new timeline_start (for undo).
    """
    tl = timeline
    starts: dict[str, float] = {}
    for tr in tl.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        tid = str(tr.get("id", "audio"))
        if track_id is not None and tid != track_id:
            continue
        if not track_uses_speech_layout(tr):
            continue
        clips = ordered_speech_clips(tr)
        t = float(anchor_time)
        if tr.get("speech_timeline_anchor") is not None:
            t = float(tr["speech_timeline_anchor"])
        for i, clip in enumerate(clips):
            cid = str(clip.get("id", ""))
            starts[cid] = t
            clip["timeline_start"] = round(t, 4)
            wall = _clip_wall_s(clip)
            t += wall
            if i + 1 < len(clips):
                gap = gap_duration_s(normalize_gap_after(clip.get("gap_after")))
                t += gap
        tr["speech_layout_mode"] = SPEECH_LAYOUT_CONTIGUOUS
        tr["clips"] = clips
    ripple_speech_linked(tl, starts)
    pack_primary_video_layout(tl)
    return starts


def _clips_by_id(timeline: dict) -> dict[str, tuple[dict, dict]]:
    out: dict[str, tuple[dict, dict]] = {}
    for tr in timeline.get("tracks") or []:
        for clip in tr.get("clips") or []:
            if isinstance(clip, dict) and clip.get("id"):
                out[str(clip["id"])] = (tr, clip)
    return out


def _primary_video_track(timeline: dict) -> dict | None:
    """First non-empty video track (main A-roll)."""
    for tr in timeline.get("tracks") or []:
        if tr.get("type") == "video" and (tr.get("clips") or []):
            return tr
    return None


def _transition_overlap_s(clip: dict) -> float:
    tr = clip.get("transition_out")
    if not isinstance(tr, dict):
        return 0.0
    try:
        return max(0.0, float(tr.get("duration") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _speech_schedule(timeline: dict) -> dict[str, dict[str, Any]]:
    """Primary speech track: clip id → start, end, pause before next, order."""
    out: dict[str, dict[str, Any]] = {}
    for tr in timeline.get("tracks") or []:
        if tr.get("type") != "audio" or not track_uses_speech_layout(tr):
            continue
        clips = ordered_speech_clips(tr)
        for i, clip in enumerate(clips):
            if not isinstance(clip, dict) or not clip.get("id"):
                continue
            if "timeline_start" not in clip:
                continue
            cid = str(clip["id"])
            start = float(clip["timeline_start"])
            wall = _clip_wall_s(clip)
            gap = (
                gap_duration_s(normalize_gap_after(clip.get("gap_after")))
                if i + 1 < len(clips)
                else 0.0
            )
            out[cid] = {
                "start": start,
                "end": start + wall,
                "gap_pause_s": gap,
                "order": i,
            }
        break
    return out


def pack_primary_video_layout(timeline: dict) -> None:
    """
    Align speech-bound video to speech starts, then abut clips when speech has no
    pause gap (removes accidental black holes between A-roll segments).
    """
    schedule = _speech_schedule(timeline)
    primary = _primary_video_track(timeline)
    if not primary:
        return
    clips = [c for c in primary.get("clips") or [] if isinstance(c, dict)]
    bound = [
        c
        for c in clips
        if isinstance(c.get("speech_bind"), str) and str(c["speech_bind"]) in schedule
    ]
    if not bound:
        _pack_track_end_to_end(primary, 0.0)
        return

    bound.sort(key=lambda c: schedule[str(c["speech_bind"])]["order"])
    for clip in bound:
        bind = str(clip["speech_bind"])
        clip["timeline_start"] = round(schedule[bind]["start"], 4)

    for i in range(len(bound) - 1):
        cur = bound[i]
        nxt = bound[i + 1]
        bind_cur = str(cur["speech_bind"])
        pause = float(schedule[bind_cur]["gap_pause_s"])
        cur_end = float(cur["timeline_start"]) + clip_timeline_duration(cur, "video")
        overlap = _transition_overlap_s(cur)
        if pause < 0.002:
            nxt["timeline_start"] = round(max(cur_end - overlap, 0.0), 4)
        else:
            speech_next = float(schedule[str(nxt["speech_bind"])]["start"])
            nxt["timeline_start"] = round(speech_next, 4)

    unbound = [c for c in clips if c not in bound]
    if unbound:
        unbound.sort(key=lambda c: float(c.get("timeline_start") or 0.0))
        anchor = 0.0
        if bound:
            last = bound[-1]
            anchor = float(last["timeline_start"]) + clip_timeline_duration(last, "video")
        _pack_track_end_to_end(primary, anchor, only=unbound)


def _pack_track_end_to_end(
    track: dict,
    start_t: float,
    *,
    only: list[dict] | None = None,
) -> None:
    """Pack clips back-to-back on a video track (non-bound b-roll gaps removed)."""
    clips = only if only is not None else [
        c for c in track.get("clips") or [] if isinstance(c, dict)
    ]
    clips = sorted(clips, key=lambda c: float(c.get("timeline_start") or 0.0))
    t = float(start_t)
    for clip in clips:
        if clip.get("allow_timeline_gap"):
            t = float(clip.get("timeline_start") or t)
        else:
            clip["timeline_start"] = round(t, 4)
        wall = clip_timeline_duration(clip, "video")
        t += wall - _transition_overlap_s(clip)


def validate_primary_video_packing(timeline: dict) -> list[str]:
    """Reject accidental black-screen gaps on the primary video track."""
    errors: list[str] = []
    primary = _primary_video_track(timeline)
    if not primary:
        return errors
    schedule = _speech_schedule(timeline)
    clips = sorted(
        [c for c in primary.get("clips") or [] if isinstance(c, dict)],
        key=lambda c: float(c.get("timeline_start") or 0.0),
    )
    if len(clips) < 2:
        return errors
    tid = str(primary.get("id", "video"))

    for i in range(len(clips) - 1):
        cur, nxt = clips[i], clips[i + 1]
        label = f"Track {tid} video clip {i}"
        if cur.get("allow_timeline_gap") or nxt.get("allow_timeline_gap"):
            continue
        try:
            a0 = float(cur["timeline_start"])
            a1 = a0 + clip_timeline_duration(cur, "video")
            b0 = float(nxt["timeline_start"])
        except (KeyError, TypeError, ValueError):
            continue
        hole = b0 - a1
        overlap_allow = _transition_overlap_s(cur)
        allowed = overlap_allow
        bind = cur.get("speech_bind")
        if isinstance(bind, str) and bind in schedule:
            allowed = max(allowed, float(schedule[bind]["gap_pause_s"]))
        if hole > allowed + 0.05:
            errors.append(
                f"{label}: {hole * 1000:.0f}ms black screen before next clip "
                f"(allowed ≤ {allowed * 1000:.0f}ms)."
            )
    return errors


def ripple_speech_linked(
    timeline: dict,
    speech_starts: dict[str, float] | None = None,
) -> None:
    """Move video/caption clips tied to speech via speech_bind or matching group_id."""
    if speech_starts is None:
        speech_starts = {}
        for tr in timeline.get("tracks") or []:
            if tr.get("type") != "audio":
                continue
            for clip in tr.get("clips") or []:
                if not isinstance(clip, dict):
                    continue
                cid = str(clip.get("id", ""))
                if cid and "timeline_start" in clip:
                    speech_starts[cid] = float(clip["timeline_start"])

    index = _clips_by_id(timeline)
    speech_walls: dict[str, float] = {}
    for sid, (tr, clip) in index.items():
        if tr.get("type") != "audio":
            continue
        speech_walls[sid] = _clip_wall_s(clip)

    for tr in timeline.get("tracks") or []:
        ttype = tr.get("type")
        if ttype not in ("video", "caption"):
            continue
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            bind = clip.get("speech_bind")
            if isinstance(bind, str) and bind in speech_starts:
                clip["timeline_start"] = round(speech_starts[bind], 4)
                continue
            gid = clip.get("group_id")
            if isinstance(gid, str):
                for sid, (atr, aclip) in index.items():
                    if atr.get("type") != "audio":
                        continue
                    if aclip.get("group_id") == gid and sid in speech_starts:
                        clip["timeline_start"] = round(speech_starts[sid], 4)
                        break


def ripple_from_clip(
    timeline: dict,
    track: dict,
    start_index: int,
) -> None:
    """Re-pack speech clips from start_index onward (after a length change)."""
    clips = ordered_speech_clips(track)
    if start_index < 0 or start_index >= len(clips):
        return
    if start_index == 0:
        anchor = float(track.get("speech_timeline_anchor", 0.0))
        build_speech_layout(timeline, track_id=str(track.get("id")), anchor_time=anchor)
        return
    prev = clips[start_index - 1]
    prev_start = float(prev["timeline_start"])
    prev_end = prev_start + _clip_wall_s(prev)
    gap = gap_duration_s(normalize_gap_after(prev.get("gap_after")))
    t = prev_end + gap
    for i in range(start_index, len(clips)):
        clip = clips[i]
        clip["timeline_start"] = round(t, 4)
        t += _clip_wall_s(clip)
        if i + 1 < len(clips):
            t += gap_duration_s(normalize_gap_after(clip.get("gap_after")))
    starts = {str(c.get("id")): float(c["timeline_start"]) for c in clips}
    ripple_speech_linked(timeline, starts)
    pack_primary_video_layout(timeline)


def validate_speech_track_gaps(track: dict, *, track_label: str) -> list[str]:
    """Fail on timeline holes/overlaps not explained by gap_after policies."""
    if not track_uses_speech_layout(track):
        return []
    if track.get("speech_layout_mode") != SPEECH_LAYOUT_CONTIGUOUS:
        return []
    errors: list[str] = []
    clips = ordered_speech_clips(track)
    for i, clip in enumerate(clips):
        if "timeline_start" not in clip:
            errors.append(f"{track_label}: speech clip {clip.get('id')} missing timeline_start.")
            continue
        try:
            t0 = float(clip["timeline_start"])
            wall = _clip_wall_s(clip)
        except (TypeError, ValueError, KeyError):
            continue
        t1 = t0 + wall
        if i + 1 >= len(clips):
            continue
        nxt = clips[i + 1]
        try:
            n0 = float(nxt["timeline_start"])
        except (TypeError, ValueError, KeyError):
            errors.append(f"{track_label}: next clip missing timeline_start.")
            continue
        actual = n0 - t1
        expected = gap_duration_s(normalize_gap_after(clip.get("gap_after")))
        if actual < -0.002:
            errors.append(
                f"{track_label}: clip {clip.get('id')} overlaps next by "
                f"{-actual * 1000:.1f}ms (not allowed on contiguous speech)."
            )
        elif abs(actual - expected) > 0.002:
            errors.append(
                f"{track_label}: accidental gap {actual * 1000:.1f}ms after "
                f"{clip.get('id')} (approved policy allows {expected * 1000:.1f}ms)."
            )
    return errors


def validate_timeline_speech_layout(timeline: dict) -> list[str]:
    errors: list[str] = []
    for tr in timeline.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        tid = str(tr.get("id", "audio"))
        if track_uses_speech_layout(tr):
            errors.extend(validate_speech_track_gaps(tr, track_label=f"Track {tid}"))
    return errors


def snapshot_timeline_starts(timeline: dict, clip_ids: set[str] | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for tr in timeline.get("tracks") or []:
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict) or "timeline_start" not in clip:
                continue
            cid = str(clip.get("id", ""))
            if clip_ids is not None and cid not in clip_ids:
                continue
            out[cid] = float(clip["timeline_start"])
    return out


def apply_timeline_starts(timeline: dict, starts: dict[str, float]) -> None:
    for tr in timeline.get("tracks") or []:
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            cid = str(clip.get("id", ""))
            if cid in starts:
                clip["timeline_start"] = round(starts[cid], 4)
    ripple_speech_linked(timeline, starts)
    pack_primary_video_layout(timeline)


def run_speech_postprocess(
    timeline: dict,
    *,
    refine_fn,
    refine_clip_ids: set[str] | None = None,
) -> tuple[dict, Any]:
    """
    Refine source trims, then layout + ripple (EDL/contiguous speech tracks only).
    refine_fn(timeline, clip_ids) -> (timeline, report)
    """
    tl = copy.deepcopy(timeline)
    detect_and_normalize_edl(tl)
    has_layout = any(
        track_uses_speech_layout(tr)
        for tr in tl.get("tracks") or []
        if tr.get("type") == "audio"
    )
    new_tl, report = refine_fn(tl, clip_ids=refine_clip_ids)
    if has_layout:
        build_speech_layout(new_tl)
    return new_tl, report
