"""Render export: clip volume, speed, and timeline duration."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from media import video_duration_seconds
from render_core import render_plan_data
from timeline_format import v2_timeline_duration


def _audio_rms_db(path: Path) -> float:
    """Mean volume in dB (more negative = quieter). Requires ffmpeg volumedetect."""
    cmd = [
        "ffmpeg",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    err = proc.stderr
    for line in err.splitlines():
        if "mean_volume:" in line:
            parts = line.split("mean_volume:")[1].strip().split()
            return float(parts[0])
    raise AssertionError("volumedetect did not report mean_volume")


def test_render_volume_half_is_quieter_than_full(
    tmp_path: Path, render_project_root: Path
) -> None:
    root = render_project_root

    def plan(volume: float) -> dict:
        return {
            "schema_version": 2,
            "tracks": [
                {
                    "id": "track-video-main",
                    "type": "video",
                    "clips": [
                        {
                            "id": "c1",
                            "source": "footage/test_a.mp4",
                            "source_in": 0.0,
                            "source_out": 1.0,
                            "timeline_start": 0.0,
                            "created_by": "user",
                            "volume": volume,
                        },
                    ],
                },
                {"id": "track-audio-main", "type": "audio", "clips": []},
                {"id": "track-caption-main", "type": "caption", "clips": []},
            ],
        }

    full_out = tmp_path / "vol_full.mp4"
    half_out = tmp_path / "vol_half.mp4"
    render_plan_data(plan(1.0), full_out, root=root)
    render_plan_data(plan(0.5), half_out, root=root)

    db_full = _audio_rms_db(full_out)
    db_half = _audio_rms_db(half_out)
    assert db_half < db_full - 3.0


def test_render_speed_doubles_shortens_output_duration(
    tmp_path: Path, render_project_root: Path
) -> None:
    root = render_project_root

    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "fast",
                        "source": "footage/test_a.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                        "speed": 2.0,
                    },
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    expected = v2_timeline_duration(plan)
    assert expected == pytest.approx(1.0, abs=0.01)

    out = tmp_path / "speed2.mp4"
    render_plan_data(plan, out, root=root)
    got = video_duration_seconds(out)
    assert got == pytest.approx(expected, abs=0.15)
