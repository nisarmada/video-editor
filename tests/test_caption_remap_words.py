"""Caption remap: follow audible sources (v2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from captions import remap_words  # noqa: E402
from timeline_format import flatten_v2_to_v1_segments  # noqa: E402


def _stub_words(stem: str) -> list[dict]:
    """Deterministic fake transcript: two words in 0..10s source time."""
    if stem != "speech":
        return []
    return [
        {"word": "hello", "start": 1.0, "end": 2.0},
        {"word": "world", "start": 3.0, "end": 4.0},
    ]


@pytest.fixture(autouse=True)
def patch_words_for_clip(monkeypatch: pytest.MonkeyPatch):
    import captions as cap

    monkeypatch.setattr(cap, "words_for_clip", _stub_words)


def _base_v2_plan() -> dict:
    return {
        "schema_version": 2,
        "settings": {"width": 1080, "height": 1920},
        "tracks": [
            {
                "id": "v1",
                "type": "video",
                "clips": [
                    {
                        "id": "vid1",
                        "created_by": "user",
                        "source": "footage/speech.mp4",
                        "source_in": 0.0,
                        "source_out": 10.0,
                        "timeline_start": 0.0,
                        "audio_source": "embedded",
                    },
                ],
            },
            {"id": "a1", "type": "audio", "clips": []},
        ],
    }


def test_untouched_embedded_matches_flattened_video_segments():
    plan = _base_v2_plan()
    old = remap_words(flatten_v2_to_v1_segments(plan), plan_data=plan)
    new = remap_words([], plan_data=plan)
    assert new == old


def test_detached_video_follows_audio_track_position():
    plan = _base_v2_plan()
    plan["tracks"][0]["clips"][0]["audio_source"] = "detached"
    plan["tracks"][1]["clips"] = [
        {
            "id": "aud1",
            "created_by": "user",
            "source": "footage/speech.mp4",
            "source_in": 0.0,
            "source_out": 10.0,
            "timeline_start": 50.0,
            "group_id": "g1",
        },
    ]
    words = remap_words([], plan_data=plan)
    assert [round(w["start"], 3) for w in words] == [51.0, 53.0]
    assert [round(w["end"], 3) for w in words] == [52.0, 54.0]


def test_embedded_plus_detached_same_speech_dedupes_words():
    plan = _base_v2_plan()
    # Embedded video still audible; duplicate audio on track (same trim)
    plan["tracks"][1]["clips"] = [
        {
            "id": "aud_dup",
            "created_by": "user",
            "source": "footage/speech.mp4",
            "source_in": 0.0,
            "source_out": 10.0,
            "timeline_start": 0.0,
        },
    ]
    words = remap_words([], plan_data=plan)
    assert len(words) == 2


def test_audio_speed_stretches_word_timeline():
    plan = _base_v2_plan()
    plan["tracks"][0]["clips"] = []
    plan["tracks"][1]["clips"] = [
        {
            "id": "aud_fast",
            "created_by": "user",
            "source": "footage/speech.mp4",
            "source_in": 0.0,
            "source_out": 10.0,
            "timeline_start": 0.0,
            "speed": 2.0,
        },
    ]
    words = remap_words([], plan_data=plan)
    # Source 1s..2s spans 1s -> at 2x speed, 0.5s on timeline
    assert [round(w["start"], 3) for w in words] == [0.5, 1.5]
    assert [round(w["end"], 3) for w in words] == [1.0, 2.0]


def test_muted_audio_track_produces_no_captions():
    plan = _base_v2_plan()
    plan["tracks"][0]["clips"] = []
    plan["tracks"][1]["muted"] = True
    plan["tracks"][1]["clips"] = [
        {
            "id": "aud1",
            "created_by": "user",
            "source": "footage/speech.mp4",
            "source_in": 0.0,
            "source_out": 10.0,
            "timeline_start": 0.0,
        },
    ]
    words = remap_words([], plan_data=plan)
    assert words == []


def test_trimmed_audio_uses_source_in_out():
    plan = _base_v2_plan()
    plan["tracks"][0]["clips"] = []
    plan["tracks"][1]["clips"] = [
        {
            "id": "aud_trim",
            "created_by": "user",
            "source": "footage/speech.mp4",
            "source_in": 2.0,
            "source_out": 8.0,
            "timeline_start": 0.0,
        },
    ]
    words = remap_words([], plan_data=plan)
    assert len(words) == 1
    assert words[0]["word"] == "world"
    assert round(words[0]["start"], 3) == 1.0
    assert round(words[0]["end"], 3) == 2.0
