"""Unified media catalog (no API)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = ROOT / "scripts"
for p in (ROOT, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backend.media_catalog import build_media_catalog  # noqa: E402
from index_cache import merged_index_path, save_json, transcript_path  # noqa: E402


def test_catalog_includes_audio_only_and_marks_video_only_analyses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir(parents=True)
    audio = tmp_path / "footage" / "voice.wav"
    video = tmp_path / "footage" / "clip.mp4"
    audio.write_bytes(b"x")
    video.write_bytes(b"x")

    # Minimal transcript for both (planner-style segment list)
    for p in (audio, video):
        save_json(
            transcript_path(p),
            {"segments": [{"start": 0.0, "end": 0.5, "text": "hi"}]},
        )
    save_json(merged_index_path(video), {"clip": video.name, "duration_seconds": 1.0})

    entries, _ = build_media_catalog(tmp_path, scope="all")
    by_name = {e["id"]: e for e in entries}
    assert by_name["voice.wav"]["kind"] == "audio"
    assert by_name["voice.wav"]["has_video"] is False
    assert by_name["voice.wav"]["analysis"]["shots"].startswith("n/a")
    assert by_name["clip.mp4"]["kind"] == "video"


def test_index_clip_merge_audio_only_without_shots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import index_clip  # noqa: E402

    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir(parents=True)
    wav = tmp_path / "footage" / "n.wav"
    wav.write_bytes(b"x")
    save_json(
        transcript_path(wav),
        {"segments": [], "clip": "n.wav", "duration_seconds": 2.0},
    )
    monkeypatch.setattr(
        index_clip,
        "clip_metadata",
        lambda p: (2.0, True, None),
    )
    merged = index_clip.build_merged_index(wav, force=True)
    assert merged["kind"] == "audio"
    assert merged["has_video"] is False
    assert "shots" not in merged
    out = merged_index_path(wav)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["transcript"]["segments"] == []
