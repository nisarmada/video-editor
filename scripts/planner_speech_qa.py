"""
Planner speech EDL quality checks (false-start spans, mock QA for tests).
"""

from __future__ import annotations

import re
from typing import Any

# Patterns the planner prompt tells the model to exclude (lowercase match).
FALSE_START_PATTERNS: tuple[str, ...] = (
    "wait, no",
    "wait no",
    "let me rephrase",
    "scratch that",
    "hang on",
    "i mean",
    "actually,",
    "sorry,",
    "false start",
)

def _false_start_match(text: str) -> bool:
    low = text.lower()
    for p in FALSE_START_PATTERNS:
        if p == "i mean":
            if re.search(r"\bi\s+mean\b", low):
                return True
        elif p in low:
            return True
    return False


def transcript_text_in_span(words: list[dict], source_in: float, source_out: float) -> str:
    parts: list[str] = []
    for w in words:
        try:
            ws = float(w["start"])
            we = float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if we <= source_in or ws >= source_out:
            continue
        parts.append(str(w.get("word", "")))
    return " ".join(parts)


def span_contains_false_start(
    words: list[dict],
    source_in: float,
    source_out: float,
) -> bool:
    """True if the trim span includes phrasing the planner must skip."""
    text = transcript_text_in_span(words, source_in, source_out)
    if not text.strip():
        return False
    return _false_start_match(text)


def audit_speech_edl_false_starts(
    plan: dict,
    words_by_source: dict[str, list[dict]],
) -> list[str]:
    """Warnings for EDL clips that still cover false-start wording."""
    warnings: list[str] = []
    for tr in plan.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        if tr.get("speech_layout_mode") != "edl":
            continue
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            src = clip.get("source")
            if not isinstance(src, str):
                continue
            words = words_by_source.get(src) or []
            if not words:
                continue
            try:
                si = float(clip["source_in"])
                so = float(clip["source_out"])
            except (KeyError, TypeError, ValueError):
                continue
            if span_contains_false_start(words, si, so):
                warnings.append(
                    f"clip {clip.get('id')}: span includes false-start phrasing "
                    f"(planner should pick a clean re-take only)"
                )
    return warnings


def mock_llm_edl_payload() -> dict[str, Any]:
    """Representative model output for unit tests (EDL + erroneous timeline times)."""
    return {
        "schema_version": 2,
        "tracks": [
            {
                "id": "V1",
                "type": "video",
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/scene.mov",
                        "source_in": 0,
                        "source_out": 5,
                        "timeline_start": 0,
                        "created_by": "ai",
                        "speech_bind": "s1",
                        "audio_source": "detached",
                    }
                ],
            },
            {
                "id": "A1",
                "type": "audio",
                "label": "Voice",
                "speech_layout_mode": "edl",
                "clips": [
                    {
                        "id": "s1",
                        "source": "footage/voice.m4a",
                        "source_in": 1.0,
                        "source_out": 3.0,
                        "timeline_start": 9.99,
                        "timeline_end": 12.0,
                        "created_by": "ai",
                        "cut_intent": {"start": "complete", "end": "complete"},
                        "gap_after": {"mode": "continuous"},
                    },
                    {
                        "id": "s2",
                        "source": "footage/voice.m4a",
                        "source_in": 4.0,
                        "source_out": 6.0,
                        "timeline_start": 15.0,
                        "created_by": "ai",
                        "gap_after": {
                            "mode": "pause",
                            "duration_s": 0.25,
                            "fill": "room_tone",
                        },
                    },
                ],
            },
        ],
    }
