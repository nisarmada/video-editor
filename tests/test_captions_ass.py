"""Unit tests for scripts/captions_ass.py ASS builder."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from caption_style_resolve import default_caption_style  # noqa: E402
from captions_ass import build_ass, build_ass_from_events  # noqa: E402


def test_build_ass_contains_dialogue_and_header():
    style = dict(default_caption_style())
    clips = [
        {
            "start": 0.0,
            "end": 1.0,
            "words": [{"word": "hello", "start": 0.0, "end": 1.0}],
            "active": {"word": "hello", "start": 0.0, "end": 1.0},
        }
    ]
    out = build_ass(clips, style, 1080, 1920)
    assert "[Script Info]" in out
    assert "Dialogue:" in out
    assert "hello" in out.lower()


def test_build_ass_from_events_matches_single_word():
    style = dict(default_caption_style())
    events = [
        {
            "start": 0.1,
            "end": 0.5,
            "chunk": [{"word": "test", "start": 0.1, "end": 0.5}],
            "active": {"word": "test", "start": 0.1, "end": 0.5},
            "style": style,
        }
    ]
    out = build_ass_from_events(events, style, 1080, 1920)
    assert "test" in out.lower()
