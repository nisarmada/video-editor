"""Energy-based acoustic word-end detection and refinement idempotency."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from audio_cut_refine import (  # noqa: E402
    acoustic_word_end,
    refine_clip_bounds,
    refine_timeline_audio_cuts,
)


def _peaks_decay(sr: float, duration: float, regions: list[tuple[float, float, float]]):
    """(t0, t1, level) piecewise constant RMS regions."""
    n = int(duration * sr) + 2
    peaks = [[0.0, 0.0] for _ in range(n)]
    for t0, t1, lv in regions:
        i0 = max(0, int(t0 * sr))
        i1 = min(n, int(t1 * sr) + 1)
        for i in range(i0, i1):
            peaks[i] = [lv, lv]
    return peaks


CFG = {
    "pre_roll_ms": 80,
    "post_roll_ms": 120,
    "snap_window_ms": 60,
    "fade_ms": 15,
    "energy_disagree_ms": 80,
    "min_clip_s": 0.2,
    "energy_end_db_below_peak": 25,
    "energy_low_hold_ms": 30,
    "acoustic_tail_ms": 60,
    "acoustic_scan_max_ms": 400,
    "tight_tail_ms": 25,
}


def test_long_decay_keeps_tail():
    words = [{"word": "hello", "start": 1.0, "end": 1.2}]
    sr = 100.0
    # Loud 1.0–1.45, quiet after 1.38 for 50ms+
    peaks = _peaks_decay(
        sr,
        3.0,
        [(1.0, 1.38, 0.5), (1.38, 1.55, 0.01), (1.55, 3.0, 0.0)],
    )
    cut, landmark, meta = acoustic_word_end(words[0], words, 0, peaks, sr, CFG)
    assert landmark >= 1.38 - 0.02
    assert cut >= 1.2 + 0.05
    assert cut >= landmark + 0.05
    assert not meta["tight"]
    _, out, *_ = refine_clip_bounds(
        1.0, 1.25, words, peaks, sr, CFG, preserve_timeline_wall=False
    )
    assert out >= cut - 0.02


def test_never_bleeds_into_next_word_onset():
    words = [
        {"word": "one", "start": 0.5, "end": 0.8},
        {"word": "two", "start": 1.0, "end": 1.3},
    ]
    sr = 100.0
    peaks = _peaks_decay(
        sr,
        2.5,
        [(0.5, 0.95, 0.4), (0.95, 1.0, 0.35), (1.0, 1.4, 0.45)],
    )
    cut, _landmark, meta = acoustic_word_end(words[0], words, 0, peaks, sr, CFG)
    assert cut < 1.0 - 0.002
    assert meta["tight"]


def test_fade_only_in_tail_after_acoustic_end():
    words = [{"word": "hi", "start": 0.2, "end": 0.5}]
    sr = 100.0
    peaks = _peaks_decay(sr, 2.0, [(0.2, 0.7, 0.4), (0.7, 2.0, 0.02)])
    clip = {"cut_intent": {"end": "complete"}}
    _in, out, _ws, _we, _fin, fout = refine_clip_bounds(
        0.2, 0.55, words, peaks, sr, CFG, clip=clip, preserve_timeline_wall=False
    )
    acoustic = float(clip["acoustic_word_end"])
    assert fout <= out - acoustic + 0.001
    assert fout <= 0.02


def test_idempotent_second_refine_pass():
    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A1",
                "type": "audio",
                "speech_layout_mode": "contiguous",
                "clips": [
                    {
                        "id": "a1",
                        "source": "footage/New_Recording_5.m4a",
                        "source_in": 1.1,
                        "source_out": 3.7,
                        "timeline_start": 0,
                        "created_by": "ai",
                        "cut_intent": {"end": "complete"},
                    }
                ],
            },
            {
                "id": "V1",
                "type": "video",
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/0118.mov",
                        "source_in": 0,
                        "source_out": 5,
                        "timeline_start": 0,
                        "created_by": "ai",
                    }
                ],
            },
        ],
    }
    if not (ROOT / "footage" / "New_Recording_5.m4a").is_file():
        pytest.skip("fixture audio missing")
    p1 = copy.deepcopy(plan)
    out1, r1 = refine_timeline_audio_cuts(p1, root=ROOT)
    c1 = out1["tracks"][0]["clips"][0]
    p2 = copy.deepcopy(out1)
    out2, r2 = refine_timeline_audio_cuts(p2, root=ROOT)
    c2 = out2["tracks"][0]["clips"][0]
    assert c1["source_in"] == pytest.approx(float(c2["source_in"]), abs=0.001)
    assert c1["source_out"] == pytest.approx(float(c2["source_out"]), abs=0.001)
    assert not r2.moves
