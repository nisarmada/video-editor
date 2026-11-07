"""Audio cut refinement: word-safe edges, fades, adjacent join."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pytest

from audio_cut_refine import (  # noqa: E402
    RefineReport,
    _apply_join_crossfades,
    refine_clip_bounds,
    refine_timeline_audio_cuts,
)


def _fake_words():
    return [
        {"word": "I", "start": 2.29, "end": 2.79},
        {"word": "remember", "start": 2.79, "end": 3.31},
        {"word": "silence,", "start": 6.33, "end": 7.09},
        {"word": "the", "start": 8.11, "end": 8.31},
    ]


def _flat_peaks(sr: float, duration: float, energized: list[tuple[float, float]]):
    n = int(duration * sr) + 1
    peaks = [[0.0, 0.0] for _ in range(n)]
    for t0, t1 in energized:
        i0 = int(t0 * sr)
        i1 = int(t1 * sr)
        for i in range(i0, min(i1, n)):
            peaks[i] = [0.2, 0.35]
    return peaks


def test_in_point_moves_before_short_i():
    words = _fake_words()
    sr = 100.0
    peaks = _flat_peaks(sr, 12.0, [(2.0, 8.0)])
    cfg = {
        "pre_roll_ms": 120,
        "post_roll_ms": 150,
        "snap_window_ms": 80,
        "fade_ms": 20,
        "energy_disagree_ms": 80,
        "min_clip_s": 0.3,
    }
    # Planner cut tight: starts at whisper "I" start
    new_in, new_out, ss, se, fin, fout = refine_clip_bounds(
        2.29, 7.2, words, peaks, sr, cfg
    )
    assert new_in < 2.29
    assert fin <= ss - new_in + 0.001
    assert new_out > new_in + 0.3
    assert 0 < fin <= 0.03

    new_in2, new_out2, *_ = refine_clip_bounds(
        2.29, 7.2, words, peaks, sr, cfg, preserve_timeline_wall=False
    )
    assert abs((new_out2 - new_in2) - (7.2 - 2.29)) > 0.02


def test_never_splits_neighbor_word():
    words = _fake_words()
    sr = 100.0
    peaks = _flat_peaks(sr, 12.0, [(7.5, 9.0)])
    cfg = {
        "pre_roll_ms": 120,
        "post_roll_ms": 150,
        "snap_window_ms": 80,
        "fade_ms": 20,
        "energy_disagree_ms": 80,
        "min_clip_s": 0.3,
    }
    new_in, new_out, ss, _se, _fin, _fout = refine_clip_bounds(
        8.05, 12.0, words, peaks, sr, cfg
    )
    assert new_in < float(words[3]["start"])
    assert new_in > float(words[2]["end"])


def test_adjacent_join_crossfade():
    clips = [
        {
            "id": "a",
            "source": "footage/x.m4a",
            "source_in": 0,
            "source_out": 2,
            "timeline_start": 0,
            "audio_fade_out": 0.02,
        },
        {
            "id": "b",
            "source": "footage/x.m4a",
            "source_in": 2,
            "source_out": 4,
            "timeline_start": 2,
            "audio_fade_in": 0.02,
        },
    ]
    _apply_join_crossfades(clips, 0.01)
    assert clips[0]["audio_fade_out"] == 0.005
    assert clips[0]["audio_fade_out"] == 0.005


def test_refinement_preserves_timeline_layout():
    plan_path = ROOT / "plans" / "7B11712B-ADD8-4E5E-BAC6-9567827A23CF_tight.json"
    if not plan_path.is_file():
        return
    from timeline_format import validate_v2_data, v2_timeline_duration, clip_timeline_duration

    data = __import__("json").loads(plan_path.read_text())
    video_starts = {
        c["id"]: (c["timeline_start"], c["source_in"], c["source_out"])
        for t in data["tracks"]
        if t["type"] == "video"
        for c in t["clips"]
    }
    out, _report = refine_timeline_audio_cuts(data, root=ROOT)
    for t in out["tracks"]:
        if t["type"] != "video":
            continue
        for c in t["clips"]:
            ts, si, so = video_starts[c["id"]]
            assert c["timeline_start"] == ts
            assert c["source_in"] == si
            assert c["source_out"] == so
    import sys

    sys.path.insert(0, str(SCRIPTS))
    from media import video_duration_seconds

    def resolve_source(raw: str):
        p = ROOT / raw
        return p

    errors, _ = validate_v2_data(
        out,
        None,
        resolve_source,
        video_duration_seconds,
    )
    assert not errors


def test_refinement_on_real_plan_fixture():
    plan_path = ROOT / "plans" / "7B11712B-ADD8-4E5E-BAC6-9567827A23CF_tight.json"
    if not plan_path.is_file():
        return
    data = __import__("json").loads(plan_path.read_text())
    before = copy.deepcopy(data)
    out, report = refine_timeline_audio_cuts(data, root=ROOT)
    assert isinstance(report, RefineReport)
    audio = next(t for t in before["tracks"] if t["type"] == "audio")
    n1_before = next(c for c in audio["clips"] if c["id"] == "n1")
    n1_after = next(
        c for t in out["tracks"] if t["type"] == "audio" for c in t["clips"] if c["id"] == "n1"
    )
    assert n1_after["source_in"] <= n1_before["source_in"]
    assert float(n1_after.get("audio_fade_in", 0)) >= 0.4
    n2_after = next(
        c for t in out["tracks"] if t["type"] == "audio" for c in t["clips"] if c["id"] == "n2"
    )
    assert float(n2_after["source_out"]) >= float(
        next(c for c in audio["clips"] if c["id"] == "n2")["source_out"]
    )
