#!/usr/bin/env python3
"""
Extract one JPEG keyframe per shot (middle of each shot) for later AI captioning.
Usage: python scripts/keyframes.py <video_path> [--force]
"""

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import (  # noqa: E402
    cache_hit,
    keyframes_dir,
    keyframes_path,
    load_json,
    save_json,
    shots_path,
)
from media import video_duration_seconds  # noqa: E402


def extract_frame(video_path: Path, time_sec: float, out_jpg: Path) -> None:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{time_sec:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_jpg),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg frame extract failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract keyframe images per shot")
    parser.add_argument("video_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_json = keyframes_path(video_path)
    if cache_hit(out_json, args.force):
        print(f"Using cached keyframes: {out_json}")
        data = load_json(out_json) or {}
        for kf in data.get("keyframes", []):
            print(f"  {kf['time']:.2f}s  ->  {kf['path']}")
        return

    shots_doc = load_json(shots_path(video_path))
    if not shots_doc:
        print(
            f"Error: run shots.py first (missing {shots_path(video_path)})",
            file=sys.stderr,
        )
        sys.exit(1)

    duration = video_duration_seconds(video_path)
    shots = shots_doc.get("shots") or []
    if not shots:
        # Static clip (no cuts detected): one keyframe at the middle
        print("No shot cuts detected; using one keyframe at mid-clip.")
        shots = [{"start": 0.0, "end": duration}]

    frame_dir = keyframes_dir(video_path)
    keyframes: list[dict] = []

    for i, shot in enumerate(shots):
        start = float(shot["start"])
        end = float(shot["end"])
        mid = min(max((start + end) / 2, 0.0), duration - 0.01)
        rel_path = Path("index") / "keyframes" / video_path.stem / f"shot_{i + 1:03d}.jpg"
        out_jpg = Path.cwd() / rel_path
        print(f"Extracting shot {i + 1} at {mid:.2f}s...")
        try:
            extract_frame(video_path, mid, out_jpg)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        keyframes.append(
            {
                "shot_index": i,
                "time": round(mid, 3),
                "path": str(rel_path).replace("\\", "/"),
            }
        )

    payload = {
        "clip": video_path.name,
        "duration_seconds": round(duration, 3),
        "keyframes": keyframes,
    }
    save_json(out_json, payload)
    print(f"Saved: {out_json}  ({len(keyframes)} frames in {frame_dir}/)")


if __name__ == "__main__":
    main()
