"""
Peak envelope for timeline waveforms (~100 peaks/sec), cached under index/<stem>_waveform.json.

FFmpeg decodes mono float32 PCM to stdout; NumPy aggregates min/max per bucket without loading
the whole decode buffer at once.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from index_cache import save_json_atomic, waveform_path  # noqa: E402
from media import clip_metadata, ffprobe_json  # noqa: E402

PEAKS_PER_SECOND = 100


def _audio_sample_rate(path: Path) -> int | None:
    data = ffprobe_json(path)
    for s in data.get("streams") or []:
        if s.get("codec_type") != "audio":
            continue
        r = s.get("sample_rate")
        if r is not None:
            try:
                return int(float(r))
            except (TypeError, ValueError):
                pass
    return None


def _pcm_f32_mono_stream(path: Path) -> subprocess.Popen[bytes]:
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def compute_waveform_peaks(clip_path: Path) -> dict:
    """
    Return payload for GET /api/footage/{name}/waveform (before caching).
    No audio: {has_audio: false, duration, sample_rate_hz_of_peaks, peaks: []}.
    """
    import numpy as np

    clip_path = clip_path.resolve()
    duration, has_audio, _rot = clip_metadata(clip_path)
    dur = round(float(duration), 6)

    if not has_audio:
        return {
            "has_audio": False,
            "duration": dur,
            "sample_rate_hz_of_peaks": float(PEAKS_PER_SECOND),
            "peaks": [],
        }

    sr = _audio_sample_rate(clip_path)
    if not sr or sr < 1:
        return {
            "has_audio": False,
            "duration": dur,
            "sample_rate_hz_of_peaks": float(PEAKS_PER_SECOND),
            "peaks": [],
        }

    bucket_samples = max(1, int(round(sr / PEAKS_PER_SECOND)))
    peaks: list[list[float]] = []

    proc = _pcm_f32_mono_stream(clip_path)
    assert proc.stdout is not None

    carry = np.array([], dtype=np.float32)

    try:
        while True:
            raw = proc.stdout.read(256 * 1024)
            if not raw:
                break
            chunk = np.frombuffer(raw, dtype=np.float32)
            carry = np.concatenate((carry, chunk))
            while len(carry) >= bucket_samples:
                b = carry[:bucket_samples]
                carry = carry[bucket_samples:]
                peaks.append([float(np.min(b)), float(np.max(b))])

        if len(carry) > 0:
            peaks.append([float(np.min(carry)), float(np.max(carry))])
    finally:
        proc.stdout.close()
        proc.wait(timeout=300)

    if proc.returncode != 0 and not peaks:
        raise RuntimeError("ffmpeg waveform decode failed (see server logs)")

    return {
        "has_audio": True,
        "duration": dur,
        "sample_rate_hz_of_peaks": float(PEAKS_PER_SECOND),
        "peaks": peaks,
    }


def compute_and_save_waveform(root: Path, clip_path: Path) -> Path:
    """Compute peaks and atomically write index/<stem>_waveform.json. Returns path written."""
    clip_path = clip_path if clip_path.is_absolute() else (root / clip_path).resolve()
    out = waveform_path(clip_path)
    data = compute_waveform_peaks(clip_path)
    save_json_atomic(out, data)
    return out
