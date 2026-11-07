"""Project canvas size flows through FFmpeg export."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from canvas_settings import even_dimension, resolve_canvas
from render_core import render_plan_data


def _video_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)
    stream = (data.get("streams") or [{}])[0]
    return int(stream["width"]), int(stream["height"])


def _minimal_plan(canvas: dict | None = None) -> dict:
    settings: dict = {"width": 1080, "height": 1920, "fps": 30}
    if canvas is not None:
        settings["canvas"] = canvas
        settings["width"] = canvas.get("width", 1080)
        settings["height"] = canvas.get("height", 1920)
        settings["fps"] = canvas.get("fps", 30)
    return {
        "schema_version": 2,
        "settings": settings,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "c1",
                        "source": "footage/test_a.mp4",
                        "source_in": 0.0,
                        "source_out": 0.5,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }


def test_resolve_canvas_defaults_without_block() -> None:
    c = resolve_canvas({"width": 1080, "height": 1920, "fps": 30})
    assert (c.width, c.height, c.fps, c.fit) == (1080, 1920, 30, "contain")


def test_even_dimension_rounds_odd() -> None:
    assert even_dimension(1081) == 1082
    assert even_dimension(1079) == 1080


def test_legacy_plan_exports_1080x1920(
    tmp_path: Path, render_project_root: Path
) -> None:
    plan = _minimal_plan(canvas=None)
    plan["settings"].pop("canvas", None)
    out = tmp_path / "legacy.mp4"
    render_plan_data(plan, out, root=render_project_root)
    assert _video_size(out) == (1080, 1920)


@pytest.mark.parametrize(
    "canvas,expected",
    [
        (
            {"width": 1080, "height": 1920, "fps": 30, "fit": "contain"},
            (1080, 1920),
        ),
        (
            {"width": 1080, "height": 1080, "fps": 30, "fit": "contain"},
            (1080, 1080),
        ),
        (
            {"width": 1920, "height": 1080, "fps": 30, "fit": "contain"},
            (1920, 1080),
        ),
    ],
)
def test_canvas_export_dimensions(
    tmp_path: Path,
    render_project_root: Path,
    canvas: dict,
    expected: tuple[int, int],
) -> None:
    out = tmp_path / f"{expected[0]}x{expected[1]}.mp4"
    render_plan_data(_minimal_plan(canvas), out, root=render_project_root)
    assert _video_size(out) == expected


def test_odd_canvas_rounded_in_export(
    tmp_path: Path, render_project_root: Path
) -> None:
    canvas = {"width": 1081, "height": 1921, "fps": 30, "fit": "contain"}
    out = tmp_path / "odd.mp4"
    render_plan_data(_minimal_plan(canvas), out, root=render_project_root)
    assert _video_size(out) == (1082, 1922)


def test_clip_cover_override_changes_aspect_fill(
    tmp_path: Path, render_project_root: Path
) -> None:
    """Portrait test clip in 16:9 canvas with cover still outputs 1920x1080."""
    plan = _minimal_plan(
        {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "fit": "contain",
        }
    )
    plan["tracks"][0]["clips"][0]["canvas_fit"] = "cover"
    out = tmp_path / "cover16x9.mp4"
    render_plan_data(plan, out, root=render_project_root)
    assert _video_size(out) == (1920, 1080)
