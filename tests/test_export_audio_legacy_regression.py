"""
Regression: v2 embedded video + empty audio tracks must match pre–audio-bus export.

Before multi-track mixing, concat audio used 44.1 kHz stereo. Legacy path (no
audio clips, no embed_audio_silent) must still produce the same PCM fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from render_core import render_plan_data

LEGACY_EXPECTED_DURATION = 1.0
# PCM hash for 1s of embedded audio from conftest lavfi clip (deterministic ffmpeg recipe).
LEGACY_PCM_SHA256 = (
    "3fac0b5168feab956d67ad0270c12db4a4bd3bac543267897688f7a09533b27c"
)


def _pcm_sha256_s16_stereo_44100(mp4: Path) -> tuple[float, str, int]:
    """Decode entire output to s16le stereo 44100; return duration, hash, byte length."""
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    dur = float(json.loads(p.stdout)["format"]["duration"])

    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-i",
            str(mp4),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    data = proc.stdout
    return dur, hashlib.sha256(data).hexdigest(), len(data)


def test_legacy_embedded_plan_audio_unchanged(
    tmp_path: Path, render_project_root: Path
) -> None:
    """Single video clip, no detached audio, no audio-track clips — same as old exporter."""
    root = render_project_root

    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "c1",
                        "source": "footage/test_a.mp4",
                        "source_in": 0.0,
                        "source_out": 1.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    },
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }

    out = tmp_path / "legacy.mp4"
    render_plan_data(plan, out, root=root)

    dur, pcm_hash, nbytes = _pcm_sha256_s16_stereo_44100(out)
    assert dur == pytest.approx(LEGACY_EXPECTED_DURATION, abs=0.05)
    assert pcm_hash == LEGACY_PCM_SHA256
    assert nbytes == pytest.approx(44100 * 2 * 2 * LEGACY_EXPECTED_DURATION, abs=4000)
