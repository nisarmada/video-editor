"""Render: refined narration in-point keeps pre-onset level below the word."""

from __future__ import annotations

import math
import struct
import subprocess
from pathlib import Path

import pytest

from audio_cut_refine import refine_timeline_audio_cuts
from render_core import render_plan_data
from timeline_format import v2_timeline_duration


def _decode_pcm_s16(path: Path) -> tuple[list[float], int]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    raw = proc.stdout
    samples = [
        s / 32768.0 for s in struct.unpack(f"<{len(raw)//2}h", raw)
    ]
    return samples, 44100


def _rms(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals))


def test_render_refined_narration_pre_onset_quieter_unchanged_duration(
    tmp_path: Path, narration_project_root: Path
) -> None:
    root = narration_project_root
    whisper_start = 1.0
    # Planner cut: starts at word (clips onset).
    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/test_a.mp4",
                        "source_in": 0.0,
                        "source_out": 0.5,
                        "timeline_start": 0.0,
                        "created_by": "user",
                        "audio_source": "detached",
                    },
                ],
            },
            {
                "id": "track-audio-main",
                "type": "audio",
                "clips": [
                    {
                        "id": "n1",
                        "source": "footage/narration.m4a",
                        "source_in": whisper_start,
                        "source_out": 1.5,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                ],
            },
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }
    wall_before = 1.5 - whisper_start
    tl_before = v2_timeline_duration(plan)

    refined, report = refine_timeline_audio_cuts(plan, root=root)
    assert report.moves, "expected refine to pull in-point before word"
    assert v2_timeline_duration(refined) == pytest.approx(tl_before, abs=0.001)
    aud = refined["tracks"][1]["clips"][0]
    wall_after = float(aud["source_out"]) - float(aud["source_in"])
    assert wall_after == pytest.approx(wall_before, abs=0.002)
    assert float(aud["source_in"]) < whisper_start

    out = tmp_path / "narration_refined.mp4"
    render_plan_data(refined, out, root=root)

    samples, sr = _decode_pcm_s16(out)
    word_at_src = whisper_start
    src_in = float(aud["source_in"])
    # Timeline t where source reaches word onset.
    word_tl = word_at_src - src_in
    i_word = int(word_tl * sr)
    i_pre = int(max(0.0, (word_tl - 0.1)) * sr)
    pre = samples[i_pre:i_word]
    word = samples[i_word : i_word + int(0.1 * sr)]
    assert _rms(pre) < _rms(word) * 0.85
