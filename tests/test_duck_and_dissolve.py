"""Ducking ramps and dissolve audio length. No paid API."""

from __future__ import annotations

import subprocess
from pathlib import Path

from edit_vocab import duck_factor_at, ffmpeg_duck_volume_filter
from media import AudioBranch, TimelinePiece, build_timeline_filter_graph


def test_duck_holds_full_level_outside_the_overlap():
    windows = [(2.0, 4.0)]
    assert duck_factor_at(1.0, windows, 0.25) == 1.0
    assert duck_factor_at(4.0, windows, 0.25) == 1.0
    assert duck_factor_at(3.0, windows, 0.25) == 0.25
    # Mid-attack (0.08s) and mid-release (0.25s) sit between full and ducked.
    attack = duck_factor_at(2.04, windows, 0.25)
    release = duck_factor_at(3.875, windows, 0.25)
    assert 0.25 < attack < 1.0
    assert 0.25 < release < 1.0
    # A gap between two windows stays loud.
    assert duck_factor_at(5.0, [(2.0, 4.0), (6.0, 7.0)], 0.25) == 1.0


def test_duck_filter_is_an_envelope_not_a_flat_gain():
    filt = ffmpeg_duck_volume_filter(1.0, [(1.0, 2.0)], 0.25)
    assert "eval=frame" in filt
    assert "1.000000" in filt
    assert "volume=0.25" not in filt


def test_duck_filter_is_accepted_by_ffmpeg(require_ffmpeg, tmp_path: Path):
    filt = ffmpeg_duck_volume_filter(0.8, [(0.4, 1.2)], 0.3)
    out = tmp_path / "ducked.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-af",
            filt,
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    assert out.stat().st_size > 0


def test_dissolve_shortens_audio_with_the_video(render_project_root: Path):
    src = render_project_root / "footage" / "test_a.mp4"
    first = TimelinePiece(
        src,
        0.0,
        2.0,
        transition_out={"type": "dissolve", "duration": 0.4},
    )
    second = TimelinePiece(src, 0.0, 2.0)
    graph, _inputs = build_timeline_filter_graph([first, second])
    assert "xfade=transition=fade:duration=0.400000" in graph
    assert "acrossfade=d=0.400000" in graph
    assert "concat=n=1:v=1:a=0" in graph
    assert "concat=n=1:v=0:a=1" in graph


def test_no_transition_keeps_separate_audio_pieces(render_project_root: Path):
    src = render_project_root / "footage" / "test_a.mp4"
    pieces = [TimelinePiece(src, 0.0, 2.0), TimelinePiece(src, 0.0, 2.0)]
    graph, _inputs = build_timeline_filter_graph(pieces)
    assert "xfade=" not in graph
    assert "acrossfade=" not in graph
    assert "concat=n=2:v=1:a=0" in graph
    assert "concat=n=2:v=0:a=1" in graph


def test_audio_branch_delay_follows_the_shortened_timeline(render_project_root: Path):
    src = render_project_root / "footage" / "test_a.mp4"
    first = TimelinePiece(
        src,
        0.0,
        2.0,
        transition_out={"type": "dissolve", "duration": 0.4},
    )
    second = TimelinePiece(src, 0.0, 2.0)
    # Editor time 2.0 is the junction. Export starts this bed 0.4s earlier.
    bed = AudioBranch(
        path=src,
        source_start=0.0,
        source_end=1.0,
        timeline_start=2.0,
        source_track_id="bed",
    )
    graph, _inputs = build_timeline_filter_graph(
        [first, second],
        audio_branches=[bed],
        timeline_total=4.0,
    )
    assert "adelay=1600|1600" in graph
    assert "adelay=2000|2000" not in graph
    assert "atrim=duration=3.600000" in graph
