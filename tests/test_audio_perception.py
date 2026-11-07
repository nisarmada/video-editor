"""Local audio perception (Part B). No paid API."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from index_cache import audio_perception_path, save_json, silences_path, transcript_path
from audio_perception import build_audio_perception


def _ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _silent_video(dest: Path, seconds: float = 2.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=30:duration={seconds}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(dest),
        ]
    )


def _music_only(dest: Path, seconds: float = 3.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(dest),
        ]
    )


def _speechish(dest: Path, seconds: float = 4.0) -> None:
    """Low tone + transcript stub so windows can classify as speech."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:sample_rate=48000:duration={seconds}",
            "-c:a",
            "aac",
            str(dest),
        ]
    )
    save_json(
        transcript_path(dest),
        {
            "clip": dest.name,
            "language": "en",
            "duration_seconds": seconds,
            "segments": [
                {
                    "start": 0.5,
                    "end": seconds - 0.5,
                    "text": "hello um world",
                    "words": [
                        {"word": "hello", "start": 0.5, "end": 1.0},
                        {"word": "um", "start": 1.0, "end": 1.2},
                        {"word": "world", "start": 1.2, "end": 1.6},
                    ],
                }
            ],
        },
    )
    save_json(silences_path(dest), {"silences": [{"start": 0.0, "end": 0.4}]})


@pytest.fixture
def audio_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, require_ffmpeg):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir()
    return tmp_path


def test_no_audio_track_reports_has_audio_false(audio_tmp: Path, require_ffmpeg):
    video = audio_tmp / "footage" / "silent.mp4"
    _silent_video(video)
    out = build_audio_perception(video, force=True)
    assert out["has_audio"] is False
    assert audio_perception_path(video).is_file()


def test_music_only_classifies_music_windows(audio_tmp: Path, require_ffmpeg):
    clip = audio_tmp / "footage" / "tone.m4a"
    _music_only(clip)
    save_json(transcript_path(clip), {"clip": clip.name, "language": "en", "segments": []})
    save_json(silences_path(clip), {"silences": []})
    out = build_audio_perception(clip, force=True)
    counts = out.get("window_class_counts") or {}
    assert counts.get("music", 0) >= 2
    assert counts.get("speech", 0) == 0
    assert out.get("loudness_lufs") is not None


def test_speech_windows_and_fillers(audio_tmp: Path, require_ffmpeg):
    clip = audio_tmp / "footage" / "talk.m4a"
    _speechish(clip)
    out = build_audio_perception(clip, force=True)
    counts = out.get("window_class_counts") or {}
    assert counts.get("speech", 0) >= 1
    assert out.get("filler_count", 0) >= 1
    assert out.get("speech_rate_wpm") is not None


def test_audio_perception_cache_hit(audio_tmp: Path, require_ffmpeg):
    clip = audio_tmp / "footage" / "tone2.m4a"
    _music_only(clip, 2.0)
    save_json(transcript_path(clip), {"clip": clip.name, "language": "en", "segments": []})
    save_json(silences_path(clip), {"silences": []})
    first = build_audio_perception(clip, force=True)
    second = build_audio_perception(clip, force=False)
    assert second == json.loads(audio_perception_path(clip).read_text(encoding="utf-8"))
    assert first["timing_ms"]["total"] == second["timing_ms"]["total"]
