"""Planner take pre-flight review payload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from index_cache import merged_index_path, save_json, takes_path, transcript_path  # noqa: E402
from planner_preflight import (  # noqa: E402
    build_take_review_groups,
    default_keep_attempt,
    excluded_time_ranges,
    take_attempt_id,
)


def test_default_keep_discards_abandoned():
    row = {"abandoned_sentence": True, "is_restart": False}
    assert default_keep_attempt(row, attempt_in_group=0, attempt_count=2) is False


@pytest.fixture
def preflight_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "backend.media_catalog.clip_metadata",
        lambda _p: (5.0, True, None),
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir()
    (tmp_path / "index").mkdir()
    clip = tmp_path / "footage" / "voice.m4a"
    clip.write_bytes(b"\x00")
    save_json(
        transcript_path(clip),
        {
            "clip": "voice.m4a",
            "segments": [
                {
                    "start": 0.0,
                    "end": 5.0,
                    "text": "Hello world. Hello world again.",
                    "words": [
                        {"word": "Hello", "start": 0.2, "end": 0.5},
                        {"word": "world.", "start": 0.6, "end": 1.0},
                        {"word": "Hello", "start": 2.0, "end": 2.3},
                        {"word": "world", "start": 2.4, "end": 2.7},
                        {"word": "again.", "start": 2.8, "end": 3.2},
                    ],
                }
            ],
        },
    )
    save_json(
        takes_path(clip),
        {
            "clip": clip.name,
            "has_speech": True,
            "phrase_groups": [{"group_index": 0, "phrase_normalized": "hello world", "attempt_count": 2}],
            "takes": [
                {
                    "take_index": 0,
                    "phrase_group": 0,
                    "attempt_in_group": 0,
                    "start": 0.2,
                    "end": 1.0,
                    "text": "Hello world",
                    "is_restart": False,
                    "abandoned_sentence": True,
                },
                {
                    "take_index": 1,
                    "phrase_group": 0,
                    "attempt_in_group": 1,
                    "start": 2.0,
                    "end": 3.2,
                    "text": "Hello world again.",
                    "is_restart": True,
                    "abandoned_sentence": False,
                },
            ],
        },
    )
    save_json(
        merged_index_path(clip),
        {"clip": clip.name, "duration_seconds": 5.0},
    )
    return tmp_path


def test_build_take_review_groups(preflight_root: Path):
    groups = build_take_review_groups(preflight_root)
    assert groups
    assert all("attempts" in g for g in groups)
    assert groups[0]["attempts"][0]["id"] == take_attempt_id("voice.m4a", 0)


def test_excluded_time_ranges(preflight_root: Path):
    groups = build_take_review_groups(preflight_root)
    aid = groups[0]["attempts"][0]["id"]
    ranges = excluded_time_ranges(preflight_root, [aid])
    assert "voice.m4a" in ranges
    assert ranges["voice.m4a"][0][0] < ranges["voice.m4a"][0][1]
