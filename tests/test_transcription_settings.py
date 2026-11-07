"""Transcription settings persisted in app_settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from transcription_settings import load_transcription_settings


def test_load_transcription_defaults_without_file(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_transcription_settings(tmp_path)
    assert cfg["model_size"] == "small"
    assert cfg["keep_quiet_speech"] is False


def test_load_transcription_from_settings_file(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    index = tmp_path / "index"
    index.mkdir()
    (index / "app_settings.json").write_text(
        json.dumps(
            {"transcription": {"model_size": "medium", "keep_quiet_speech": True}}
        ),
        encoding="utf-8",
    )
    cfg = load_transcription_settings(tmp_path)
    assert cfg["model_size"] == "medium"
    assert cfg["keep_quiet_speech"] is True
