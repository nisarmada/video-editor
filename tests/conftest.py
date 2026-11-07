"""Shared pytest config: repo on PYTHONPATH + FFmpeg render fixtures."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Deterministic lavfi clip: 3s, 320x240 test pattern + 440 Hz tone @ 44100 Hz.
_RENDER_CLIP_DURATION_S = 3.0


@pytest.fixture(scope="session")
def require_ffmpeg() -> None:
    """Skip when ffmpeg/ffprobe are unavailable; never skip for a missing media file."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not on PATH")
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not on PATH")


def _write_test_a_mp4(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate=30:duration={_RENDER_CLIP_DURATION_S}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=44100:duration={_RENDER_CLIP_DURATION_S}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-tune",
        "stillimage",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def render_project_root(tmp_path: Path, require_ffmpeg, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Minimal project tree under tmp_path with generated footage/test_a.mp4.
    Validates plans relative to this root (never writes into repo footage/).
    """
    (tmp_path / "plans").mkdir()
    (tmp_path / "output").mkdir()
    _write_test_a_mp4(tmp_path / "footage" / "test_a.mp4")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_narration_m4a(dest: Path) -> None:
    """Low tone then loud tone; word onset ~1.0s for transcript alignment."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:sample_rate=44100:duration=0.95",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=44100:duration=1.55",
        "-filter_complex",
        "[0:a]volume=0.05[lo];[1:a]volume=0.35[hi];"
        "[lo][hi]concat=n=2:v=0:a=1,apad=pad_dur=2.5",
        "-t",
        "2.5",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _write_narration_index(root: Path, stem: str) -> None:
    """Transcript + coarse waveform peaks for audio_cut_refine."""
    import json

    idx = root / "index"
    idx.mkdir(parents=True, exist_ok=True)
    transcript = {
        "clip": f"{stem}.m4a",
        "segments": [
            {
                "start": 0.92,
                "end": 1.5,
                "text": "Hi",
                "words": [{"word": "Hi", "start": 1.0, "end": 1.35}],
            }
        ],
    }
    (idx / f"{stem}_transcript.json").write_text(
        json.dumps(transcript, indent=2) + "\n",
        encoding="utf-8",
    )
    sr = 100.0
    n = int(2.5 * sr) + 1
    peaks: list[list[float]] = []
    for i in range(n):
        t = i / sr
        amp = 0.02 if t < 0.92 else 0.35
        peaks.append([-amp, amp])
    waveform = {
        "has_audio": True,
        "duration": 2.5,
        "sample_rate_hz_of_peaks": sr,
        "peaks": peaks,
    }
    (idx / f"{stem}_waveform.json").write_text(
        json.dumps(waveform) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def narration_project_root(render_project_root: Path) -> Path:
    """render_project_root plus narration.m4a + index artifacts."""
    root = render_project_root
    _write_narration_m4a(root / "footage" / "narration.m4a")
    _write_narration_index(root, "narration")
    return root
