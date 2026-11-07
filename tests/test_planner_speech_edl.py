"""Planner speech EDL: layout, strip LLM times, false-start QA."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from planner_speech_qa import (  # noqa: E402
    audit_speech_edl_false_starts,
    mock_llm_edl_payload,
    span_contains_false_start,
)
from speech_layout import (  # noqa: E402
    build_speech_layout,
    detect_and_normalize_edl,
    gap_duration_s,
    validate_speech_track_gaps,
)
from plan import BASE_SYSTEM_PROMPT  # noqa: E402


def test_prompt_forbids_speech_timeline_fields():
    assert "Forbidden on speech EDL clips" in BASE_SYSTEM_PROMPT
    assert "timeline_start" in BASE_SYSTEM_PROMPT
    assert "gap_after" in BASE_SYSTEM_PROMPT
    assert "Wait, no" in BASE_SYSTEM_PROMPT or "wait, no" in BASE_SYSTEM_PROMPT.lower()


def test_mock_edl_laid_out_contiguously():
    plan = mock_llm_edl_payload()
    detect_and_normalize_edl(plan)
    build_speech_layout(plan)
    tr = next(t for t in plan["tracks"] if t["id"] == "A1")
    c1, c2 = tr["clips"]
    assert c1["timeline_start"] == 0.0
    assert c2["timeline_start"] == pytest.approx(2.0 + gap_duration_s(c1.get("gap_after")))
    assert not validate_speech_track_gaps(tr, track_label="A1")


def test_llm_timeline_start_on_speech_edl_is_stripped():
    plan = mock_llm_edl_payload()
    assert plan["tracks"][1]["clips"][0].get("timeline_start") == 9.99
    detect_and_normalize_edl(plan)
    for clip in plan["tracks"][1]["clips"]:
        assert "timeline_start" not in clip or clip.get("speech_order") is not None
    build_speech_layout(plan)
    assert plan["tracks"][1]["clips"][0]["timeline_start"] == 0.0
    assert "timeline_end" not in plan["tracks"][1]["clips"][0]


def test_false_start_span_detected():
    words = [
        {"word": "Wait,", "start": 0.5, "end": 0.8},
        {"word": "no", "start": 0.8, "end": 1.0},
        {"word": "I", "start": 1.2, "end": 1.4},
        {"word": "meant", "start": 1.4, "end": 1.8},
    ]
    assert span_contains_false_start(words, 0.4, 1.1)
    assert not span_contains_false_start(words, 1.2, 2.0)


def test_audit_flags_false_start_clip():
    plan = mock_llm_edl_payload()
    words = {
        "footage/voice.m4a": [
            {"word": "Let", "start": 1.0, "end": 1.2},
            {"word": "me", "start": 1.2, "end": 1.4},
            {"word": "rephrase", "start": 1.4, "end": 2.0},
        ]
    }
    plan["tracks"][1]["clips"][0]["source_in"] = 1.0
    plan["tracks"][1]["clips"][0]["source_out"] = 2.0
    warns = audit_speech_edl_false_starts(plan, words)
    assert any("s1" in w for w in warns)


def test_clean_take_span_passes_audit():
    plan = mock_llm_edl_payload()
    words = {
        "footage/voice.m4a": [
            {"word": "Hello", "start": 1.0, "end": 1.5},
            {"word": "world.", "start": 1.5, "end": 2.0},
        ]
    }
    warns = audit_speech_edl_false_starts(plan, words)
    assert not warns
