"""Export applies track volume × clip volume; track volume 1.0 matches legacy."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = ROOT / "scripts"
for p in (ROOT, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import subprocess

import pytest

from render_core import collect_audio_branches, render_plan_data  # noqa: E402
from timeline_format import flatten_v2_to_v1_segments  # noqa: E402


def _audio_plan(*, track_volume: float | None, clip_volume: float = 0.8) -> dict:
    track: dict = {
        "id": "track-audio-main",
        "type": "audio",
        "clips": [
            {
                "id": "a1",
                "source": "footage/voice.wav",
                "source_in": 0.0,
                "source_out": 2.0,
                "timeline_start": 0.0,
                "created_by": "user",
                "volume": clip_volume,
            },
        ],
    }
    if track_volume is not None:
        track["volume"] = track_volume
    return {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/clip.mp4",
                        "source_in": 0.0,
                        "source_out": 1.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                ],
            },
            track,
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }


def test_audio_branches_unchanged_when_track_volume_is_one_or_omitted(tmp_path):
    root = tmp_path
    wav = root / "footage" / "voice.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"x")

    explicit = _audio_plan(track_volume=1.0)
    omitted = _audio_plan(track_volume=None)

    b1 = collect_audio_branches(explicit, root)
    b2 = collect_audio_branches(omitted, root)
    assert len(b1) == len(b2) == 1
    assert b1[0].volume == b2[0].volume == 0.8


def test_audio_branches_multiply_track_and_clip_volume(tmp_path):
    root = tmp_path
    wav = root / "footage" / "voice.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"x")

    plan = _audio_plan(track_volume=0.5, clip_volume=0.8)
    branches = collect_audio_branches(plan, root)
    assert len(branches) == 1
    assert branches[0].volume == 0.4


def test_flatten_video_embedded_volume_unchanged_when_track_volume_one():
    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "volume": 1.0,
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/a.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                        "volume": 0.6,
                    },
                ],
            },
        ],
    }
    no_track_vol = copy.deepcopy(plan)
    del no_track_vol["tracks"][0]["volume"]

    segs_a = flatten_v2_to_v1_segments(plan)
    segs_b = flatten_v2_to_v1_segments(no_track_vol)
    assert segs_a[0].get("volume") == segs_b[0].get("volume") == 0.6


def test_flatten_video_embedded_volume_applies_track_gain():
    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "volume": 0.5,
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/a.mp4",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                        "volume": 0.8,
                    },
                ],
            },
        ],
    }
    segs = flatten_v2_to_v1_segments(plan)
    assert segs[0].get("volume") == 0.4


def _audio_mean_db(path: Path) -> float:
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
    for line in proc.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].strip().split()[0])
    raise AssertionError("volumedetect missing")


def _make_tone_mp4(path: Path, duration: float = 1.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-nostats",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x240:d={duration}",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_embedded_video_track_volume_halves_audio_not_quarters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Track vol 0.5 × clip vol 1.0 → ~6dB drop, not ~12dB (no double apply)."""
    root = tmp_path
    monkeypatch.chdir(root)
    src = root / "footage" / "tone.mp4"
    _make_tone_mp4(src)

    def embedded_plan(track_volume: float | None) -> dict:
        tr: dict = {
            "id": "track-video-main",
            "type": "video",
            "clips": [
                {
                    "id": "v1",
                    "source": "footage/tone.mp4",
                    "source_in": 0.0,
                    "source_out": 1.0,
                    "timeline_start": 0.0,
                    "created_by": "user",
                },
            ],
        }
        if track_volume is not None:
            tr["volume"] = track_volume
        return {"schema_version": 2, "tracks": [tr]}

    full = tmp_path / "full.mp4"
    half = tmp_path / "half.mp4"
    render_plan_data(embedded_plan(None), full, root=root)
    render_plan_data(embedded_plan(0.5), half, root=root)

    db_full = _audio_mean_db(full)
    db_half = _audio_mean_db(half)
    assert db_half < db_full - 4.0
    assert db_half > db_full - 9.0
