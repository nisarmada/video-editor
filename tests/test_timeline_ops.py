"""Tests for v2 timeline edit operations."""

from __future__ import annotations

import copy

import pytest

from timeline_ops import (
    add_clip,
    apply_undo,
    batch_operations,
    delete_clip,
    dispatch_operation,
    merge_clips,
    move_clip,
    remove_track,
    set_clip_property,
    split_clip,
    trim_clip,
    trim_timeline_edge,
)


def sample_timeline() -> dict:
    return {
        "schema_version": 2,
        "name": "test",
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-1",
                        "source": "footage/a.mp4",
                        "source_in": 0.0,
                        "source_out": 6.0,
                        "timeline_start": 0.0,
                        "created_by": "ai",
                        "group_id": "g1",
                        "zoom": 1.1,
                    },
                    {
                        "id": "clip-2",
                        "source": "footage/b.mp4",
                        "source_in": 1.0,
                        "source_out": 4.0,
                        "timeline_start": 6.0,
                        "created_by": "user",
                    },
                ],
            },
            {
                "id": "track-caption-main",
                "type": "caption",
                "clips": [],
            },
        ],
    }


def video_clips(timeline: dict) -> list[dict]:
    for t in timeline["tracks"]:
        if t["type"] == "video":
            return sorted(t["clips"], key=lambda c: c["timeline_start"])
    return []


def test_split_then_merge_restores_original_clip():
    original = sample_timeline()
    before = copy.deepcopy(video_clips(original)[0])

    split = split_clip(original, clip_id="clip-1", at_timeline_time=2.0)
    after_split = video_clips(split["timeline"])
    assert len(after_split) == 3
    left, right = after_split[0], after_split[1]
    assert left["id"] == "clip-1"
    assert left["source_in"] == 0.0
    assert left["source_out"] == pytest.approx(2.0)
    assert left["timeline_start"] == 0.0
    assert left["created_by"] == "ai"
    assert left["group_id"] == "g1"
    assert right["source_in"] == pytest.approx(2.0)
    assert right["source_out"] == 6.0
    assert right["timeline_start"] == pytest.approx(2.0)

    merged = merge_clips(
        split["timeline"],
        clip_id_a=left["id"],
        clip_id_b=right["id"],
    )
    restored = video_clips(merged["timeline"])[0]
    assert restored["id"] == before["id"]
    assert restored["source_in"] == before["source_in"]
    assert restored["source_out"] == before["source_out"]
    assert restored["timeline_start"] == before["timeline_start"]
    assert restored["created_by"] == before["created_by"]
    assert restored["group_id"] == before["group_id"]
    assert restored.get("zoom") == before.get("zoom")


def test_split_undo_payload_is_merge():
    result = split_clip(sample_timeline(), clip_id="clip-1", at_timeline_time=3.0)
    undo = result["undo"]
    assert undo["op"] == "merge_clips"
    back = merge_clips(
        result["timeline"],
        clip_id_a=undo["clip_id_a"],
        clip_id_b=undo["clip_id_b"],
    )
    assert video_clips(back["timeline"])[0]["source_out"] == 6.0


def test_trim_clip_and_undo():
    tl = sample_timeline()
    trimmed = trim_clip(tl, clip_id="clip-1", source_in=0.5, source_out=5.5)
    c = video_clips(trimmed["timeline"])[0]
    assert c["source_in"] == 0.5
    assert c["source_out"] == 5.5

    restored = apply_undo(trimmed["timeline"], trimmed["undo"])
    c2 = video_clips(restored["timeline"])[0]
    assert c2["source_in"] == 0.0
    assert c2["source_out"] == 6.0


def test_move_clip_changes_track_and_start():
    tl = sample_timeline()
    moved = move_clip(
        tl,
        clip_id="clip-2",
        track_id="track-caption-main",
        timeline_start=10.0,
    )
    cap_track = next(t for t in moved["timeline"]["tracks"] if t["id"] == "track-caption-main")
    assert len(cap_track["clips"]) == 1
    assert cap_track["clips"][0]["timeline_start"] == 10.0
    video = next(t for t in moved["timeline"]["tracks"] if t["id"] == "track-video-main")
    assert len(video["clips"]) == 1

    back = apply_undo(moved["timeline"], moved["undo"])
    assert len(video_clips(back["timeline"])) == 2


def test_delete_and_add_undo():
    tl = sample_timeline()
    deleted = delete_clip(tl, clip_id="clip-2")
    assert len(video_clips(deleted["timeline"])) == 1

    back = apply_undo(deleted["timeline"], deleted["undo"])
    assert len(video_clips(back["timeline"])) == 2


def test_add_clip_rejects_overlap():
    tl = sample_timeline()
    with pytest.raises(ValueError, match="overlap"):
        add_clip(
            tl,
            track_id="track-video-main",
            clip={
                "id": "clip-x",
                "source": "footage/c.mp4",
                "source_in": 0.0,
                "source_out": 2.0,
                "timeline_start": 5.0,
                "created_by": "user",
            },
        )


def test_add_clip_without_track_id_uses_first_video_track():
    tl = sample_timeline()
    added = add_clip(
        tl,
        track_id=None,
        clip={
            "id": "clip-new",
            "source": "footage/d.mp4",
            "source_in": 0.0,
            "source_out": 1.0,
            "timeline_start": 12.0,
            "created_by": "user",
        },
    )
    vids = video_clips(added["timeline"])
    assert any(c["id"] == "clip-new" for c in vids)


def test_add_clip_without_track_id_creates_video_track_when_missing():
    tl: dict = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-audio-only",
                "type": "audio",
                "clips": [],
            },
        ],
    }
    added = add_clip(
        tl,
        track_id=None,
        clip={
            "id": "clip-v",
            "source": "footage/d.mp4",
            "source_in": 0.0,
            "source_out": 1.0,
            "timeline_start": 0.0,
            "created_by": "user",
        },
    )
    tracks = added["timeline"]["tracks"]
    assert any(t.get("type") == "video" for t in tracks)
    vtrack = next(t for t in tracks if t.get("type") == "video")
    assert len(vtrack.get("clips") or []) == 1
    assert added["undo"]["op"] == "remove_track"


def test_remove_track_undo_restores():
    tl: dict = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "tv",
                "type": "video",
                "clips": [
                    {
                        "id": "c1",
                        "source": "footage/a.mp4",
                        "source_in": 0.0,
                        "source_out": 1.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                ],
            },
        ],
    }
    rem = remove_track(tl, track_id="tv")
    assert not any(t.get("id") == "tv" for t in rem["timeline"]["tracks"])
    back = apply_undo(rem["timeline"], rem["undo"])
    assert any(t.get("id") == "tv" for t in back["timeline"]["tracks"])


def test_merge_requires_adjacent_same_source():
    tl = sample_timeline()
    with pytest.raises(ValueError, match="adjacent|source"):
        merge_clips(tl, clip_id_a="clip-1", clip_id_b="clip-2")

    split = split_clip(tl, clip_id="clip-1", at_timeline_time=2.0)
    part_a = {
        "id": "part-a",
        "source": "footage/a.mp4",
        "source_in": 0.0,
        "source_out": 1.0,
        "timeline_start": 12.0,
        "created_by": "user",
    }
    part_b = {
        "id": "part-b",
        "source": "footage/a.mp4",
        "source_in": 1.0,
        "source_out": 2.0,
        "timeline_start": 13.0,
        "created_by": "user",
    }
    added = add_clip(split["timeline"], track_id="track-video-main", clip=part_a)
    added2 = add_clip(added["timeline"], track_id="track-video-main", clip=part_b)
    merge_clips(added2["timeline"], clip_id_a="part-a", clip_id_b="part-b")


def test_set_clip_property_undo():
    tl = sample_timeline()
    updated = set_clip_property(tl, clip_id="clip-1", properties={"zoom": 1.5, "group_id": "g2"})
    c = video_clips(updated["timeline"])[0]
    assert c["zoom"] == 1.5
    assert c["group_id"] == "g2"

    back = apply_undo(updated["timeline"], updated["undo"])
    c2 = video_clips(back["timeline"])[0]
    assert c2["zoom"] == 1.1
    assert c2["group_id"] == "g1"


def test_dispatch_operation_unknown():
    with pytest.raises(ValueError, match="Unknown operation"):
        dispatch_operation(sample_timeline(), "nope", {})


def test_split_rejects_exterior_time():
    with pytest.raises(ValueError, match="strictly inside"):
        split_clip(sample_timeline(), clip_id="clip-1", at_timeline_time=0.0)


def test_trim_timeline_edge_start_and_undo():
    tl = sample_timeline()
    out = trim_timeline_edge(tl, clip_id="clip-1", edge="start", at_timeline_time=2.0)
    c = video_clips(out["timeline"])[0]
    assert c["timeline_start"] == pytest.approx(2.0)
    assert c["source_in"] == pytest.approx(2.0)
    back = apply_undo(out["timeline"], out["undo"])
    c2 = video_clips(back["timeline"])[0]
    assert c2["timeline_start"] == pytest.approx(0.0)
    assert c2["source_in"] == pytest.approx(0.0)


def test_batch_operations_two_splits_one_undo():
    tl = sample_timeline()
    batch = batch_operations(
        tl,
        steps=[
            {
                "operation": "split_clip",
                "arguments": {"clip_id": "clip-1", "at_timeline_time": 2.0},
            },
            {
                "operation": "split_clip",
                "arguments": {"clip_id": "clip-2", "at_timeline_time": 7.0},
            },
        ],
    )
    v = video_clips(batch["timeline"])
    assert len(v) == 4
    assert batch["undo"]["op"] == "sequence"
    back = apply_undo(batch["timeline"], batch["undo"])
    assert len(video_clips(back["timeline"])) == 2
