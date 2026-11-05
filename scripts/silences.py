#!/usr/bin/env python3
"""
Detect silent stretches in a clip with ffmpeg silencedetect.
Usage: python scripts/silences.py <video_path> [--noise DB] [--min-duration SEC] [--force]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import cache_hit, load_json, save_json, silences_path  # noqa: E402
from media import video_duration_seconds  # noqa: E402

DEFAULT_NOISE_DB = -35.0
DEFAULT_MIN_DURATION = 0.4

_SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")


def detect_silences(
    video_path: Path,
    noise_db: float,
    min_duration: float,
) -> list[dict]:
    """Run silencedetect and return [{start, end}, ...]."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(video_path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg silencedetect failed")

    log = result.stderr
    silences: list[dict] = []
    current_start: float | None = None
    for line in log.splitlines():
        m_start = _SILENCE_START.search(line)
        if m_start:
            current_start = float(m_start.group(1))
            continue
        m_end = _SILENCE_END.search(line)
        if m_end and current_start is not None:
            end = float(m_end.group(1))
            silences.append(
                {"start": round(current_start, 3), "end": round(end, 3)}
            )
            current_start = None
    return silences


def print_report(silences: list[dict], duration: float) -> None:
    silent_total = sum(s["end"] - s["start"] for s in silences)
    print(f"Clip length: {duration:.2f}s")
    print(f"Silent regions: {len(silences)}  ({silent_total:.2f}s total silent)")
    for s in silences:
        print(f"  [{s['start']:.2f} -> {s['end']:.2f}]  ({s['end'] - s['start']:.2f}s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect silences in a video clip")
    parser.add_argument("video_path", help="Path to video under footage/ or elsewhere")
    parser.add_argument(
        "--noise",
        type=float,
        default=DEFAULT_NOISE_DB,
        help=f"silencedetect noise threshold in dB (default {DEFAULT_NOISE_DB})",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=DEFAULT_MIN_DURATION,
        help=f"Minimum silence length in seconds (default {DEFAULT_MIN_DURATION})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run detection even if index JSON already exists",
    )
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_path = silences_path(video_path)
    if cache_hit(out_path, args.force):
        cached = load_json(out_path)
        if (
            isinstance(cached, dict)
            and cached.get("noise_db") == args.noise
            and cached.get("min_duration_seconds") == args.min_duration
        ):
            silences = cached.get("silences", [])
            duration = float(cached.get("duration_seconds", 0))
            print(f"Using cached silences: {out_path}")
            print_report(silences, duration)
            return

    duration = video_duration_seconds(video_path)
    print(
        f"Detecting silences (noise={args.noise}dB, min={args.min_duration}s)..."
    )
    try:
        silences = detect_silences(video_path, args.noise, args.min_duration)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "clip": video_path.name,
        "duration_seconds": round(duration, 3),
        "noise_db": args.noise,
        "min_duration_seconds": args.min_duration,
        "silences": silences,
    }
    save_json(out_path, payload)
    print(f"Saved: {out_path}\n")
    print_report(silences, duration)


if __name__ == "__main__":
    main()
