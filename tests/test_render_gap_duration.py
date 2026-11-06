"""v2 export: gaps on the video timeline extend output duration like the preview."""

from __future__ import annotations

from pathlib import Path

import pytest

from media import video_duration_seconds
from render_core import render_plan_data
from timeline_format import v2_timeline_duration


def test_rendered_duration_matches_timeline_end_with_gap(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    root = repo
    footage = root / "footage" / "test_a.mp4"
    assert footage.is_file(), f"missing test fixture: {footage}"

    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "gap-before",
                        "source": "footage/test_a.mp4",
                        "source_in": 0.0,
                        "source_out": 1.0,
                        "timeline_start": 2.0,
                        "created_by": "user",
                    },
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    expected = v2_timeline_duration(plan)
    assert expected == pytest.approx(3.0, abs=0.02)

    out = tmp_path / "with_gap.mp4"
    render_plan_data(plan, out, root=root)
    got = video_duration_seconds(out)
    assert got == pytest.approx(expected, abs=0.2)
