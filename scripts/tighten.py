#!/usr/bin/env python3
"""
One-command tighten: transcribe (if needed), silences, plan, render.
Usage: python scripts/tighten.py footage/clip.mp4 [--remove-fillers] [--force-index]
"""

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import silences  # noqa: E402
import tighten_plan  # noqa: E402
import transcribe  # noqa: E402
from index_cache import cache_hit, load_json, silences_path, transcript_path  # noqa: E402
from render import main as render_main  # noqa: E402


def ensure_transcript(video: Path, force: bool) -> None:
    out = transcript_path(video)
    if cache_hit(out, force):
        print(f"Using cached transcript: {out}")
        return
    print("Running transcription...")
    old_argv = sys.argv
    sys.argv = ["transcribe.py", str(video)]
    try:
        transcribe.main()
    finally:
        sys.argv = old_argv


def ensure_silences(
    video: Path,
    force: bool,
    noise: float,
    min_duration: float,
) -> None:
    out = silences_path(video)
    if cache_hit(out, force):
        cached = load_json(out)
        if (
            cached
            and cached.get("noise_db") == noise
            and cached.get("min_duration_seconds") == min_duration
        ):
            print(f"Using cached silences: {out}")
            return

    print("Detecting silences...")
    old_argv = sys.argv
    sys.argv = [
        "silences.py",
        str(video),
        "--noise",
        str(noise),
        "--min-duration",
        str(min_duration),
    ]
    if force:
        sys.argv.append("--force")
    try:
        silences.main()
    finally:
        sys.argv = old_argv


def run_tighten_plan(video: Path, remove_fillers: bool) -> Path:
    old_argv = sys.argv
    sys.argv = ["tighten_plan.py", str(video)]
    if remove_fillers:
        sys.argv.append("--remove-fillers")
    try:
        tighten_plan.main()
    finally:
        sys.argv = old_argv
    return Path.cwd() / "plans" / f"{video.stem}_tight.json"


def run_render(plan: Path, output: Path) -> None:
    old_argv = sys.argv
    sys.argv = ["render.py", str(plan), str(output)]
    try:
        render_main()
    finally:
        sys.argv = old_argv


def main() -> None:
    parser = argparse.ArgumentParser(description="Tighten one clip end-to-end")
    parser.add_argument("video_path")
    parser.add_argument("--remove-fillers", action="store_true")
    parser.add_argument(
        "--force-index",
        action="store_true",
        help="Re-run transcript and silence detection",
    )
    parser.add_argument("--noise", type=float, default=-35.0)
    parser.add_argument("--min-duration", type=float, default=0.4)
    args = parser.parse_args()

    video = Path(args.video_path)
    if not video.is_file():
        print(f"Error: file not found: {video}", file=sys.stderr)
        sys.exit(1)

    ensure_transcript(video, args.force_index)
    ensure_silences(video, args.force_index, args.noise, args.min_duration)

    plan_path = run_tighten_plan(video, args.remove_fillers)
    output_path = Path.cwd() / "output" / f"{video.stem}_tight.mp4"
    run_render(plan_path, output_path)
    print(f"\nAll done: {output_path}")


if __name__ == "__main__":
    main()
