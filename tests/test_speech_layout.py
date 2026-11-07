"""Speech EDL layout, gap policies, ripple, validation."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audio_cut_refine import refine_clip_bounds  # noqa: E402
from speech_layout import (  # noqa: E402
    SPEECH_LAYOUT_CONTIGUOUS,
    SPEECH_LAYOUT_EDL,
    build_speech_layout,
    gap_duration_s,
    mark_speech_edl_track,
    pack_primary_video_layout,
    ripple_speech_linked,
    validate_primary_video_packing,
    validate_timeline_speech_layout,
    validate_speech_track_gaps,
)
from timeline_ops import apply_undo, relayout_speech  # noqa: E402


def _speech_track(clips: list[dict], **extra) -> dict:
    tr = {
        "id": "A1",
        "type": "audio",
        "label": "Voice",
        "speech_layout_mode": SPEECH_LAYOUT_EDL,
        "clips": clips,
        **extra,
    }
    mark_speech_edl_track(tr)
    return tr


def test_v2_timeline_duration_skips_clips_without_timeline_start():
    from timeline_format import v2_timeline_duration

    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
            },
        ]
    )
    tl = {"schema_version": 2, "tracks": [tr]}
    assert v2_timeline_duration(tl) == 0.0


def test_validate_plan_parsed_runs_speech_layout_before_validate():
    from plan import validate_plan_parsed

    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
            },
        ]
    )
    tl = {
        "schema_version": 2,
        "tracks": [
            tr,
            {"id": "V1", "type": "video", "clips": []},
        ],
    }
    # refine_timeline_audio_cuts deep-copies; validation must not KeyError on speech EDL.
    errors = validate_plan_parsed(tl, "25s reel", 25.0)
    assert isinstance(errors, list)


def test_back_to_back_layout():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
            },
            {
                "id": "a2",
                "source": "footage/x.m4a",
                "source_in": 3.0,
                "source_out": 4.0,
                "created_by": "ai",
            },
        ]
    )
    tl = {"schema_version": 2, "tracks": [tr, {"id": "V1", "type": "video", "clips": []}]}
    build_speech_layout(tl)
    a1, a2 = tr["clips"]
    assert a1["timeline_start"] == 0.0
    assert a2["timeline_start"] == pytest.approx(2.0)
    assert tr["speech_layout_mode"] == SPEECH_LAYOUT_CONTIGUOUS
    assert not validate_speech_track_gaps(tr, track_label="A1")


def test_gap_policy_pause():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 1.0,
                "created_by": "ai",
                "gap_after": {"mode": "pause", "duration_s": 0.25, "fill": "room_tone"},
            },
            {
                "id": "a2",
                "source": "footage/x.m4a",
                "source_in": 2.0,
                "source_out": 3.0,
                "created_by": "ai",
            },
        ]
    )
    tl = {"schema_version": 2, "tracks": [tr]}
    build_speech_layout(tl)
    assert tr["clips"][1]["timeline_start"] == pytest.approx(1.25)
    assert gap_duration_s(tr["clips"][0]["gap_after"]) == pytest.approx(0.25)


def test_validate_rejects_accidental_gap():
    tr = {
        "id": "A1",
        "type": "audio",
        "speech_layout_mode": SPEECH_LAYOUT_CONTIGUOUS,
        "clips": [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 1.0,
                "created_by": "ai",
                "timeline_start": 0.0,
                "speech_order": 0,
                "gap_after": {"mode": "continuous"},
            },
            {
                "id": "a2",
                "source": "footage/x.m4a",
                "source_in": 2.0,
                "source_out": 3.0,
                "created_by": "ai",
                "timeline_start": 1.5,
                "speech_order": 1,
            },
        ],
    }
    errs = validate_speech_track_gaps(tr, track_label="A1")
    assert any("accidental gap" in e for e in errs)


def test_pack_primary_video_abuts_on_continuous_speech():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
                "gap_after": {"mode": "continuous"},
            },
            {
                "id": "a2",
                "source": "footage/x.m4a",
                "source_in": 2.0,
                "source_out": 4.0,
                "created_by": "ai",
            },
        ]
    )
    video = {
        "id": "V1",
        "type": "video",
        "clips": [
            {
                "id": "v1",
                "source": "footage/v.mov",
                "source_in": 0,
                "source_out": 1.0,
                "timeline_start": 0.0,
                "created_by": "ai",
                "speech_bind": "a1",
                "audio_source": "detached",
            },
            {
                "id": "v2",
                "source": "footage/v.mov",
                "source_in": 1.0,
                "source_out": 2.0,
                "timeline_start": 2.5,
                "created_by": "ai",
                "speech_bind": "a2",
                "audio_source": "detached",
            },
        ],
    }
    tl = {"schema_version": 2, "tracks": [video, tr]}
    build_speech_layout(tl)
    assert video["clips"][1]["timeline_start"] == pytest.approx(1.0)


def test_validate_primary_video_rejects_black_gap():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
                "gap_after": {"mode": "continuous"},
            },
            {
                "id": "a2",
                "source": "footage/x.m4a",
                "source_in": 2.0,
                "source_out": 4.0,
                "created_by": "ai",
            },
        ]
    )
    tr["speech_layout_mode"] = SPEECH_LAYOUT_CONTIGUOUS
    tr["clips"][0]["timeline_start"] = 0.0
    tr["clips"][1]["timeline_start"] = 2.0
    video = {
        "id": "V1",
        "type": "video",
        "clips": [
            {
                "id": "v1",
                "source": "footage/v.mov",
                "source_in": 0,
                "source_out": 1.0,
                "timeline_start": 0.0,
                "created_by": "ai",
                "speech_bind": "a1",
            },
            {
                "id": "v2",
                "source": "footage/v.mov",
                "source_in": 1.0,
                "source_out": 2.0,
                "timeline_start": 2.0,
                "created_by": "ai",
                "speech_bind": "a2",
            },
        ],
    }
    tl = {"schema_version": 2, "tracks": [video, tr]}
    errs = validate_primary_video_packing(tl)
    assert any("black screen" in e for e in errs)


def test_pack_only_via_pack_primary_video_layout():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
                "gap_after": {"mode": "continuous"},
            },
        ]
    )
    tr["speech_layout_mode"] = SPEECH_LAYOUT_CONTIGUOUS
    tr["clips"][0]["timeline_start"] = 0.0
    video = {
        "id": "V1",
        "type": "video",
        "clips": [
            {
                "id": "v1",
                "source": "footage/v.mov",
                "source_in": 0,
                "source_out": 1.0,
                "timeline_start": 0.0,
                "created_by": "ai",
                "speech_bind": "a1",
            },
        ],
    }
    tl = {"schema_version": 2, "tracks": [video, tr]}
    pack_primary_video_layout(tl)
    assert video["clips"][0]["timeline_start"] == 0.0


def test_ripple_speech_bind():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
            },
        ]
    )
    video = {
        "id": "v1",
        "type": "video",
        "clips": [
            {
                "id": "v1",
                "source": "footage/v.mov",
                "source_in": 0,
                "source_out": 2,
                "timeline_start": 9.0,
                "created_by": "ai",
                "speech_bind": "a1",
                "audio_source": "detached",
            }
        ],
    }
    tl = {"schema_version": 2, "tracks": [video, tr]}
    build_speech_layout(tl)
    assert video["clips"][0]["timeline_start"] == 0.0


def test_relayout_undo_restores_starts():
    tr = _speech_track(
        [
            {
                "id": "a1",
                "source": "footage/x.m4a",
                "source_in": 0.0,
                "source_out": 2.0,
                "created_by": "ai",
            },
        ]
    )
    tr["speech_layout_mode"] = SPEECH_LAYOUT_CONTIGUOUS
    tr["clips"][0]["timeline_start"] = 5.0
    tl = {"schema_version": 2, "tracks": [tr]}
    before = copy.deepcopy(tl)
    res = relayout_speech(tl, refine=False)
    assert res["timeline"]["tracks"][0]["clips"][0]["timeline_start"] == 0.0
    back = apply_undo(res["timeline"], res["undo"])
    assert back["timeline"]["tracks"][0]["clips"][0]["timeline_start"] == 5.0


def test_refine_without_wall_preserve_changes_duration():
    words = [
        {"word": "hi", "start": 1.0, "end": 1.4},
        {"word": "there", "start": 1.4, "end": 1.9},
    ]
    peaks = [[0.0, 0.0] for _ in range(200)]
    for i in range(100, 140):
        peaks[i] = [0.2, 0.3]
    sr = 100.0
    cfg = {
        "pre_roll_ms": 80,
        "post_roll_ms": 120,
        "snap_window_ms": 60,
        "fade_ms": 20,
        "energy_disagree_ms": 80,
        "min_clip_s": 0.3,
    }
    wall_before = 2.0 - 1.2
    new_in, new_out, *_ = refine_clip_bounds(
        1.2, 2.0, words, peaks, sr, cfg, preserve_timeline_wall=False
    )
    assert new_in < 1.2
    assert abs((new_out - new_in) - wall_before) > 0.05
