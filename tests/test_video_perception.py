"""Local video perception (Part A). No paid API."""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from index_cache import load_json, perception_path, save_json, shots_path
from video_perception import (
    build_video_perception,
    motion_level,
    shake_score,
)


def _gray_canvas(value: int, noise: float = 0.0, shape=(180, 320)) -> np.ndarray:
    base = np.full(shape, value, dtype=np.uint8)
    if noise > 0:
        rng = np.random.default_rng(42)
        base = np.clip(base.astype(np.float32) + rng.normal(0, noise, shape), 0, 255).astype(
            np.uint8
        )
    return base


def _checker(shift_x: int = 0, shape=(180, 320)) -> np.ndarray:
    h, w = shape
    y, x = np.ogrid[:h, :w]
    grid = ((x + shift_x) // 16 + y // 16) % 2
    return (grid * 180 + 40).astype(np.uint8)


def test_shake_score_orders_steady_below_jittered():
    steady = [_checker(0) for _ in range(8)]
    jittered = [_checker((i % 5) * 3) for i in range(8)]
    assert shake_score(steady) < shake_score(jittered)
    assert motion_level(steady) < motion_level(jittered)


def _write_test_mp4(dest: Path, seconds: float = 3.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate=30:duration={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-tune",
        "stillimage",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def perception_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, require_ffmpeg):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir()
    video = tmp_path / "footage" / "steady.mp4"
    _write_test_mp4(video, 2.5)
    save_json(
        shots_path(video),
        {
            "clip": video.name,
            "duration_seconds": 2.5,
            "threshold": 27.0,
            "shots": [{"start": 0.0, "end": 2.5}],
        },
    )
    return video


def test_video_perception_cache_hit(perception_clip: Path):
    first = build_video_perception(perception_clip, force=True)
    assert first.get("shots")
    shot = first["shots"][0]
    assert shot.get("palette_rgb")
    assert shot.get("mean_brightness") is not None
    assert shot.get("motion_level") is not None
    assert len(shot.get("vision_frames") or []) >= 1
    for frame in shot["vision_frames"]:
        jpg = Path.cwd() / frame["path"]
        assert jpg.is_file()
        assert jpg.stat().st_size > 0
        im = cv2.imread(str(jpg))
        assert im is not None
        long_edge = max(im.shape[0], im.shape[1])
        assert long_edge <= 520

    second = build_video_perception(perception_clip, force=False)
    assert second["timing_ms"]["total"] == first["timing_ms"]["total"]
    assert load_json(perception_path(perception_clip)) == second
