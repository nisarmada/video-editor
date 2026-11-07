"""Speech takes grouping (Part C). No paid API."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from index_cache import save_json, takes_path, transcript_path
from takes import build_takes, phrase_similarity


def _ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _tiny_audio(dest: Path, seconds: float = 30.0) -> None:
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


def _three_attempts_transcript(clip: Path) -> None:
    """Three near-duplicate attempts at the same hook line."""
    words = []
    segments = []
    t = 0.5
    lines = [
        ("Welcome to my channel and", False),
        ("Welcome to my channel and today", False),
        ("Welcome to my channel and today.", True),
    ]
    for text, _complete in lines:
        seg_words = []
        for token in text.split():
            seg_words.append(
                {
                    "word": token,
                    "start": round(t, 3),
                    "end": round(t + 0.25, 3),
                }
            )
            t += 0.28
        words.extend(seg_words)
        segments.append(
            {
                "start": seg_words[0]["start"],
                "end": seg_words[-1]["end"],
                "text": text,
                "words": seg_words,
            }
        )
        t += 1.4  # pause before next attempt

    save_json(
        transcript_path(clip),
        {
            "clip": clip.name,
            "language": "en",
            "duration_seconds": t,
            "segments": segments,
        },
    )


@pytest.fixture
def takes_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, require_ffmpeg):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir()
    return tmp_path


def test_phrase_similarity_detects_duplicates():
    a = "Welcome to my channel and"
    b = "Welcome to my channel and today"
    assert phrase_similarity(a, b) >= 0.62


def test_three_attempts_single_phrase_group(takes_tmp: Path, require_ffmpeg):
    clip = takes_tmp / "footage" / "takes.m4a"
    _tiny_audio(clip, 25.0)
    _three_attempts_transcript(clip)
    out = build_takes(clip, force=True)
    groups = out.get("phrase_groups") or []
    takes = out.get("takes") or []
    assert len(groups) == 1
    assert len(takes) == 3
    assert takes[0]["is_restart"] is False
    assert takes[1]["is_restart"] is True
    assert takes[2]["ends_complete_sentence"] is True
    assert takes[0]["abandoned_sentence"] is True
    assert takes[1]["abandoned_sentence"] is True


def test_no_speech_empty_takes(takes_tmp: Path, require_ffmpeg):
    clip = takes_tmp / "footage" / "empty.m4a"
    _tiny_audio(clip, 2.0)
    save_json(
        transcript_path(clip),
        {"clip": clip.name, "language": "en", "segments": []},
    )
    out = build_takes(clip, force=True)
    assert out["has_speech"] is False
    assert out.get("takes") == []


def test_takes_cache_hit(takes_tmp: Path, require_ffmpeg):
    clip = takes_tmp / "footage" / "cached.m4a"
    _tiny_audio(clip, 5.0)
    _three_attempts_transcript(clip)
    first = build_takes(clip, force=True)
    second = build_takes(clip, force=False)
    assert second == json.loads(takes_path(clip).read_text(encoding="utf-8"))
    assert first["timing_ms"]["total"] == second["timing_ms"]["total"]
