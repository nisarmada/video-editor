"""Export speech-cut verification (synthetic PCM)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from speech_cut_audit import audit_timeline_speech_cuts  # noqa: E402
from verify_export import (  # noqa: E402
    measure_at_timeline,
    validate_export_report,
)


def _make_samples_with_hard_cut(sr: int, cut_t: float) -> list[float]:
    n = int(2.0 * sr)
    out = [0.0] * n
    cut_i = int(cut_t * sr)
    for i in range(cut_i - int(0.2 * sr), cut_i):
        out[i] = 0.45
    return out


def test_hard_discontinuity_flags_problem():
    sr = 44100
    samples = _make_samples_with_hard_cut(sr, 0.6)
    m = measure_at_timeline(samples, sr, 0.6, next_timeline_start=1.2)
    assert m["problems"], m


def test_measure_returns_metrics_keys():
    sr = 44100
    samples = [0.0] * sr
    m = measure_at_timeline(samples, sr, 0.5, next_timeline_start=1.0)
    assert "exported_decay_retained_ms" in m["metrics"]
    assert "exported_click_score" in m["metrics"]


def test_validate_export_report_catches_bad_boundary():
    timeline = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A1",
                "type": "audio",
                "clips": [
                    {
                        "id": "a1",
                        "source": "footage/x.m4a",
                        "source_in": 0,
                        "source_out": 1,
                        "timeline_start": 0,
                        "created_by": "user",
                        "speech_cut_quality": {
                            "decay_retained_ms": 5,
                            "click_score": 0.4,
                            "energy_at_cut_db_below_peak": -5,
                        },
                        "cut_intent": {"end": "complete"},
                    }
                ],
            },
            {"id": "V1", "type": "video", "clips": []},
        ],
    }
    report = audit_timeline_speech_cuts(timeline)
    errs = validate_export_report(report)
    assert errs


def test_nudge_speech_cut_undo():
    from timeline_ops import apply_undo, nudge_speech_cut

    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A1",
                "type": "audio",
                "speech_layout_mode": "contiguous",
                "clips": [
                    {
                        "id": "a1",
                        "source": "footage/x.m4a",
                        "source_in": 0.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                        "speech_order": 0,
                    }
                ],
            }
        ],
    }
    r = nudge_speech_cut(tl, clip_id="a1", edge="out", delta_ms=10)
    assert r["timeline"]["tracks"][0]["clips"][0]["source_out"] == pytest.approx(2.01)
    back = apply_undo(r["timeline"], r["undo"])
    assert back["timeline"]["tracks"][0]["clips"][0]["source_out"] == pytest.approx(2.0)
