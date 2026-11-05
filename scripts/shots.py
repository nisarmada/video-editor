#!/usr/bin/env python3
"""
Detect shot boundaries with PySceneDetect (content-based cuts).
Usage: python scripts/shots.py <video_path> [--threshold N] [--force]
"""

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import cache_hit, load_json, save_json, shots_path  # noqa: E402
from media import video_duration_seconds  # noqa: E402

DEFAULT_THRESHOLD = 27.0


def detect_shots(video_path: Path, threshold: float) -> list[dict]:
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold))
    manager.detect_scenes(video)
    scene_list = manager.get_scene_list()

    shots: list[dict] = []
    for start_tc, end_tc in scene_list:
        shots.append(
            {
                "start": round(start_tc.seconds, 3),
                "end": round(end_tc.seconds, 3),
            }
        )
    return shots


def print_report(shots: list[dict], duration: float) -> None:
    print(f"Clip length: {duration:.2f}s  |  Shots: {len(shots)}")
    for i, shot in enumerate(shots):
        length = shot["end"] - shot["start"]
        print(
            f"  [{i + 1}] {shot['start']:.2f}s - {shot['end']:.2f}s  ({length:.2f}s)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect shot cuts in a video")
    parser.add_argument("video_path")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"ContentDetector threshold (default {DEFAULT_THRESHOLD}; lower = more cuts)",
    )
    parser.add_argument("--force", action="store_true", help="Re-run even if cached")
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_path = shots_path(video_path)
    if cache_hit(out_path, args.force):
        cached = load_json(out_path)
        if (
            isinstance(cached, dict)
            and cached.get("threshold") == args.threshold
        ):
            shots = cached.get("shots", [])
            duration = float(cached.get("duration_seconds", 0))
            print(f"Using cached shots: {out_path}")
            print_report(shots, duration)
            return

    duration = video_duration_seconds(video_path)
    print(f"Detecting shots (threshold={args.threshold})...")
    try:
        shots = detect_shots(video_path, args.threshold)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "clip": video_path.name,
        "duration_seconds": round(duration, 3),
        "threshold": args.threshold,
        "shots": shots,
    }
    save_json(out_path, payload)
    print(f"Saved: {out_path}\n")
    print_report(shots, duration)


if __name__ == "__main__":
    main()
