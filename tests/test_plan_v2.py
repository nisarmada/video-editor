"""Planner v1 → v2 conversion (no API)."""

from __future__ import annotations

from convert_v1_to_v2 import convert
from plan import finalize_v2_plan
from timeline_format import get_track, is_v2


def test_convert_applies_planner_created_by_and_group():
    v1 = {
        "name": "test_plan",
        "brief": "10s test",
        "segments": [
            {
                "source": "footage/a.mp4",
                "start": 0.0,
                "end": 2.0,
                "caption": "hello",
                "reason": "hook",
            },
            {
                "source": "footage/b.mp4",
                "start": 1.0,
                "end": 4.0,
                "caption": "world",
                "reason": "body",
            },
        ],
    }
    v2 = convert(v1, created_by="ai", group_id="run-group-abc")
    assert is_v2(v2)
    for track in v2["tracks"]:
        for clip in track.get("clips") or []:
            assert clip["created_by"] == "ai"
            if track.get("type") == "caption":
                assert "group_id" not in clip
            else:
                assert clip["group_id"] == "run-group-abc"


def test_finalize_v2_plan(monkeypatch):
    v1 = {
        "name": "test_plan",
        "segments": [
            {
                "source": "footage/a.mp4",
                "start": 0.0,
                "end": 2.0,
                "caption": "hi",
                "reason": "hook",
            },
        ],
    }
    monkeypatch.setattr("plan.validate_segments", lambda segs, target: [])
    monkeypatch.setattr(
        "plan.validate_plan_data",
        lambda data, target: ([], []),
    )

    v2 = finalize_v2_plan(v1, "10s test brief", "group-xyz")
    video = get_track(v2, "video")
    assert len(video["clips"]) == 1
    assert video["clips"][0]["created_by"] == "ai"
    assert video["clips"][0]["group_id"] == "group-xyz"
    cap = get_track(v2, "caption")
    assert "group_id" not in cap["clips"][0]
