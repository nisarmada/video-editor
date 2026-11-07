#!/usr/bin/env python3
"""
Local audio measurements: LUFS, loudness range, 1s class windows, speech rate,
fillers, and pauses. Uses transcript + silences when present. No paid API.

Usage: python scripts/audio_perception.py <media_path> [--force]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import (  # noqa: E402
    audio_perception_path,
    cache_hit,
    load_json,
    save_json,
    silences_path,
    transcript_path,
)
from media import clip_metadata  # noqa: E402
from transcribe import has_audio_track, video_duration_seconds  # noqa: E402

WINDOW_SECONDS = 1.0
ANALYSIS_SAMPLE_RATE = 8000
# RMS below this (dBFS) is treated as silence in a window.
SILENCE_RMS_DB = -50.0
MUSIC_RMS_DB = -38.0
MUSIC_FLATNESS_MAX = 0.35

_I_LUFS_LINE = re.compile(r"^\s*I:\s*(-?[0-9.]+)\s*LUFS", re.MULTILINE)
_LRA_LINE = re.compile(r"^\s*LRA:\s*(-?[0-9.]+)\s*LU", re.MULTILINE)

# Normalized tokens (lowercase, no punctuation).
FILLERS: dict[str, set[str]] = {
    "en": {
        "um",
        "uh",
        "uhh",
        "erm",
        "hmm",
        "like",
        "basically",
        "literally",
        "actually",
    },
    "es": {"eh", "este", "pues", "tipo", "bueno", "o", "sea"},
    "fr": {"euh", "ben", "quoi", "genre", "voila"},
    "de": {"äh", "also", "quasi", "halt"},
}


def _language_key(code: str | None) -> str:
    if not code:
        return "en"
    base = str(code).split("-")[0].lower()
    return base if base in FILLERS else "en"


def decode_mono_pcm(path: Path, sample_rate: int = ANALYSIS_SAMPLE_RATE) -> np.ndarray:
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
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("ffmpeg audio decode failed")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def loudness_ebur128(path: Path) -> tuple[float | None, float | None]:
    """Integrated LUFS and loudness range (LU) from ffmpeg ebur128."""
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, None
    log = (result.stderr or "") + (result.stdout or "")
    integrated = None
    lra = None
    i_matches = _I_LUFS_LINE.findall(log)
    if i_matches:
        integrated = round(float(i_matches[-1]), 2)
    lra_matches = _LRA_LINE.findall(log)
    if lra_matches:
        lra = round(float(lra_matches[-1]), 2)
    return integrated, lra


def rms_db(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    power = float(np.mean(samples * samples))
    if power <= 1e-12:
        return -120.0
    return 20.0 * float(np.log10(np.sqrt(power)))


def spectral_flatness(samples: np.ndarray) -> float:
    if samples.size < 64:
        return 1.0
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64)))
    spectrum = np.maximum(spectrum, 1e-12)
    geo = float(np.exp(np.mean(np.log(spectrum))))
    arith = float(np.mean(spectrum))
    return geo / arith if arith > 0 else 1.0


def collect_words(transcript: dict) -> list[dict]:
    words: list[dict] = []
    for seg in transcript.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        for w in seg.get("words") or []:
            if not isinstance(w, dict):
                continue
            try:
                words.append(
                    {
                        "word": str(w.get("word") or "").strip(),
                        "start": float(w["start"]),
                        "end": float(w["end"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    words.sort(key=lambda item: item["start"])
    return words


def overlap_seconds(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def silence_fraction_in_window(
    t0: float, t1: float, silences: list[dict]
) -> float:
    span = max(1e-6, t1 - t0)
    covered = 0.0
    for s in silences:
        if not isinstance(s, dict):
            continue
        try:
            covered += overlap_seconds(t0, t1, float(s["start"]), float(s["end"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(1.0, covered / span)


def words_in_window(t0: float, t1: float, words: list[dict]) -> list[dict]:
    out: list[dict] = []
    for w in words:
        if w["end"] <= t0 or w["start"] >= t1:
            continue
        out.append(w)
    return out


def classify_window(
    t0: float,
    t1: float,
    samples: np.ndarray,
    *,
    words: list[dict],
    silences: list[dict],
) -> dict:
    rms = rms_db(samples)
    flat = spectral_flatness(samples)
    win_words = words_in_window(t0, t1, words)
    sil_frac = silence_fraction_in_window(t0, t1, silences)

    if rms <= SILENCE_RMS_DB or sil_frac >= 0.55:
        window_class = "silence"
    elif win_words:
        window_class = "speech"
    elif rms >= MUSIC_RMS_DB and flat <= MUSIC_FLATNESS_MAX:
        window_class = "music"
    else:
        window_class = "ambience"

    return {
        "start": round(t0, 3),
        "end": round(t1, 3),
        "class": window_class,
        "rms_db": round(rms, 2),
        "flatness": round(flat, 4),
        "speech_word_count": len(win_words),
        "silence_overlap": round(sil_frac, 3),
    }


def count_fillers(words: list[dict], language: str) -> int:
    lang = _language_key(language)
    tokens = FILLERS.get(lang, FILLERS["en"])
    # Also count two-word fillers in English.
    bigrams = {("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")}
    count = 0
    normalized = [
        re.sub(r"[^a-z0-9']+", "", (w.get("word") or "").lower()) for w in words
    ]
    normalized = [t for t in normalized if t]
    for i, token in enumerate(normalized):
        if token in tokens:
            count += 1
        if i + 1 < len(normalized):
            pair = (token, normalized[i + 1])
            if lang == "en" and pair in bigrams:
                count += 1
    return count


def speech_rate_wpm(words: list[dict], duration: float) -> float | None:
    if not words or duration <= 0:
        return None
    if len(words) < 2:
        span = duration
    else:
        span = max(0.1, float(words[-1]["end"]) - float(words[0]["start"]))
    return round(len(words) / (span / 60.0), 1)


def pause_stats(
    words: list[dict], silences: list[dict], duration: float
) -> tuple[float | None, float | None]:
    gaps: list[float] = []
    for i in range(1, len(words)):
        gap = float(words[i]["start"]) - float(words[i - 1]["end"])
        if gap > 0.05:
            gaps.append(gap)
    for s in silences:
        if not isinstance(s, dict):
            continue
        try:
            gaps.append(float(s["end"]) - float(s["start"]))
        except (KeyError, TypeError, ValueError):
            continue
    if duration <= 0:
        return None, None
    pause_time = sum(gaps)
    longest = max(gaps) if gaps else 0.0
    ratio = round(min(1.0, pause_time / duration), 4)
    return ratio, round(longest, 3)


def build_audio_perception(media_path: Path, *, force: bool = False) -> dict:
    media_path = media_path.resolve()
    out_path = audio_perception_path(media_path)
    if cache_hit(out_path, force) and not force:
        data = load_json(out_path)
        if isinstance(data, dict):
            return data

    duration_meta, has_audio, _ = clip_metadata(media_path)
    duration = float(video_duration_seconds(media_path) or duration_meta or 0.0)

    if not has_audio_track(media_path):
        payload = {
            "clip": media_path.name,
            "has_audio": False,
            "duration_seconds": round(duration, 6),
            "version": 1,
        }
        save_json(out_path, payload)
        return payload

    transcript = load_json(transcript_path(media_path)) or {}
    silences_doc = load_json(silences_path(media_path)) or {}
    silences = silences_doc.get("silences") if isinstance(silences_doc, dict) else []
    if not isinstance(silences, list):
        silences = []

    words = collect_words(transcript if isinstance(transcript, dict) else {})
    language = (transcript.get("language") if isinstance(transcript, dict) else None) or "unknown"

    t0 = time.perf_counter()
    pcm = decode_mono_pcm(media_path)
    lufs, lra = loudness_ebur128(media_path)

    windows: list[dict] = []
    bucket = int(ANALYSIS_SAMPLE_RATE * WINDOW_SECONDS)
    n_windows = max(1, int(np.ceil(duration / WINDOW_SECONDS)))
    counts = {"speech": 0, "music": 0, "ambience": 0, "silence": 0}

    for i in range(n_windows):
        start_t = i * WINDOW_SECONDS
        end_t = min(duration, start_t + WINDOW_SECONDS)
        i0 = int(start_t * ANALYSIS_SAMPLE_RATE)
        i1 = int(end_t * ANALYSIS_SAMPLE_RATE)
        chunk = pcm[i0:i1] if i1 <= len(pcm) else pcm[i0:]
        row = classify_window(start_t, end_t, chunk, words=words, silences=silences)
        windows.append(row)
        counts[row["class"]] = counts.get(row["class"], 0) + 1

    pause_ratio, longest_pause = pause_stats(words, silences, duration)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    payload = {
        "clip": media_path.name,
        "has_audio": True,
        "duration_seconds": round(duration, 6),
        "language": language,
        "version": 1,
        "loudness_lufs": lufs,
        "loudness_range_lu": lra,
        "dynamic_range_db": lra,
        "speech_rate_wpm": speech_rate_wpm(words, duration),
        "filler_count": count_fillers(words, str(language)),
        "pause_ratio": pause_ratio,
        "longest_pause_s": longest_pause,
        "window_seconds": WINDOW_SECONDS,
        "windows": windows,
        "window_class_counts": counts,
        "timing_ms": {"total": elapsed_ms},
    }
    save_json(out_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Local audio perception")
    parser.add_argument("media_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    path = Path(args.media_path)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    out_path = audio_perception_path(path)
    if cache_hit(out_path, args.force) and not args.force:
        print(f"Using cached audio perception: {out_path}")
        return

    try:
        payload = build_audio_perception(path, force=args.force)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    counts = payload.get("window_class_counts") or {}
    print(
        f"Saved: {out_path}  LUFS={payload.get('loudness_lufs')}  "
        f"windows speech={counts.get('speech', 0)} music={counts.get('music', 0)} "
        f"silence={counts.get('silence', 0)}"
    )


if __name__ == "__main__":
    main()
