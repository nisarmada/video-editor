"""
Round-trip each timeline op with its published inverse (undo payload).

Runs: dispatch_operation(op) -> apply_undo(undo). After split, delete, trim, move,
add, merge, the result should match the original (merge allows a new UUID on the
right segment after undo).

When adding a new operation to timeline_ops, extend this file and confirm undo works.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from timeline_ops import apply_undo, dispatch_operation


def _deep_sort_clips(timeline: dict) -> dict:
    """Copy with clips per track sorted by timeline_start for stable comparison."""
    out = copy.deepcopy(timeline)
    for track in out.get("tracks") or []:
        clips = track.get("clips") or []
        track["clips"] = sorted(clips, key=lambda c: float(c["timeline_start"]))
    return out


def _approx_equal(a: Any, b: Any) -> bool:
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return False
    if isinstance(a, float) and isinstance(b, (int, float)):
        return a == pytest.approx(float(b), rel=1e-5, abs=1e-5)
    if isinstance(a, (int, float)) and isinstance(b, float):
        return float(a) == pytest.approx(b, rel=1e-5, abs=1e-5)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_approx_equal(a[k], b[k]) for k in sorted(a.keys()))
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_approx_equal(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def assert_timelines_equal(a: dict, b: dict) -> None:
    assert _approx_equal(_deep_sort_clips(a), _deep_sort_clips(b))


def assert_merge_undo_restores_semantics(before: dict, after: dict) -> None:
    """Merge undo is split_clip: right segment gets a new id; compare geometry."""
    t0 = _deep_sort_clips(before)
    t1 = _deep_sort_clips(after)
    assert len(t0["tracks"]) == len(t1["tracks"])
    for tr0, tr1 in zip(t0["tracks"], t1["tracks"], strict=True):
        assert tr0["id"] == tr1["id"]
        c0 = tr0.get("clips") or []
        c1 = tr1.get("clips") or []
        assert len(c0) == len(c1)
        for clip0, clip1 in zip(
            sorted(c0, key=lambda c: float(c["timeline_start"])),
            sorted(c1, key=lambda c: float(c["timeline_start"])),
            strict=True,
        ):
            for key in ("source", "source_in", "source_out", "timeline_start", "created_by"):
                if key in clip0 or key in clip1:
                    assert _approx_equal(clip0.get(key), clip1.get(key)), (
                        f"mismatch {key}: {clip0.get(key)} vs {clip1.get(key)}"
                    )


def _run_roundtrip(timeline: dict, operation: str, arguments: dict) -> dict:
    """Forward op via dispatch_operation, inverse via apply_undo (same as API apply_undo)."""
    first = dispatch_operation(copy.deepcopy(timeline), operation, arguments)
    second = apply_undo(copy.deepcopy(first["timeline"]), first["undo"])
    return second["timeline"]


def test_roundtrip_split_clip():
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-a",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 10.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    }
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    restored = _run_roundtrip(
        tl,
        "split_clip",
        {"clip_id": "clip-a", "at_timeline_time": 3.0},
    )
    assert_timelines_equal(tl, restored)


def test_roundtrip_delete_clip():
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-a",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    }
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    restored = _run_roundtrip(tl, "delete_clip", {"clip_id": "clip-a"})
    assert_timelines_equal(tl, restored)


def test_roundtrip_trim_clip():
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-a",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 10.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    }
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    restored = _run_roundtrip(
        tl,
        "trim_clip",
        {"clip_id": "clip-a", "source_in": 1.0, "source_out": 9.0},
    )
    assert_timelines_equal(tl, restored)


def test_roundtrip_move_clip():
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-a",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                    {
                        "id": "clip-b",
                        "source": "footage/y.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 3.0,
                        "created_by": "user",
                    },
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    restored = _run_roundtrip(
        tl,
        "move_clip",
        {"clip_id": "clip-a", "timeline_start": 5.0},
    )
    assert_timelines_equal(tl, restored)


def test_roundtrip_add_clip():
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-a",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    }
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    new_clip = {
        "id": "clip-b",
        "source": "footage/y.mp4",
        "source_in": 0.0,
        "source_out": 2.0,
        "timeline_start": 5.0,
        "created_by": "user",
    }
    restored = _run_roundtrip(
        tl,
        "add_clip",
        {"track_id": "track-video-main", "clip": new_clip},
    )
    assert_timelines_equal(tl, restored)


def test_roundtrip_merge_clips():
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "c1",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                    {
                        "id": "c2",
                        "source": "footage/x.mp4",
                        "source_in": 2.0,
                        "source_out": 4.5,
                        "timeline_start": 2.0,
                        "created_by": "user",
                    },
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    restored = _run_roundtrip(
        tl,
        "merge_clips",
        {"clip_id_a": "c1", "clip_id_b": "c2"},
    )
    # Undo of merge is split: right clip id is regenerated — compare source/timeline only.
    assert_merge_undo_restores_semantics(tl, restored)


def test_roundtrip_apply_undo_via_dispatch_matches_apply_undo():
    """API path: apply_undo as operation with {undo: payload}."""
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-a",
                        "source": "footage/x.mp4",
                        "source_in": 0.0,
                        "source_out": 5.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    }
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    first = dispatch_operation(
        copy.deepcopy(tl),
        "delete_clip",
        {"clip_id": "clip-a"},
    )
    via_fn = apply_undo(copy.deepcopy(first["timeline"]), first["undo"])["timeline"]
    via_dispatch = dispatch_operation(
        copy.deepcopy(first["timeline"]),
        "apply_undo",
        {"undo": first["undo"]},
    )["timeline"]
    assert_timelines_equal(via_fn, via_dispatch)
    assert_timelines_equal(tl, via_fn)
