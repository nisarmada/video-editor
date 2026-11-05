#!/usr/bin/env python3
"""
Cut a segment from a video and save as a new file (re-encoded for accuracy).
Usage: python scripts/cut.py <input> <start_seconds> <end_seconds> <output>
"""

import subprocess
import sys
from pathlib import Path

# Reuse ffprobe helper from probe.py in the same folder
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from probe import get_video_info  # noqa: E402


def duration_seconds(path: Path) -> float:
    data = get_video_info(path)
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        return float(fmt["duration"])
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and stream.get("duration"):
            return float(stream["duration"])
    raise RuntimeError("Could not determine video duration")


def output_in_footage(output: Path) -> bool:
    """True if output would be written inside footage/ (project-relative)."""
    cwd = Path.cwd().resolve()
    footage = (cwd / "footage").resolve()
    out = output.resolve()
    if out == footage:
        return True
    try:
        out.relative_to(footage)
        return True
    except ValueError:
        return False


def main() -> None:
    if len(sys.argv) != 5:
        print(
            "Usage: python scripts/cut.py <input> <start_seconds> <end_seconds> <output>",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[4])

    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if output_in_footage(output_path):
        print("Error: refusing to write output into footage/", file=sys.stderr)
        sys.exit(1)

    try:
        start = float(sys.argv[2])
        end = float(sys.argv[3])
    except ValueError:
        print("Error: start and end must be numbers (seconds)", file=sys.stderr)
        sys.exit(1)

    if start >= end:
        print("Error: start must be less than end", file=sys.stderr)
        sys.exit(1)

    try:
        total = duration_seconds(input_path)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if end > total + 0.01:
        print(
            f"Error: end ({end}s) is past clip duration ({total:.3f}s)",
            file=sys.stderr,
        )
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Re-encode for frame-accurate cuts that play everywhere
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ss",
        str(start),
        "-to",
        str(end),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            result.stderr.strip() or "ffmpeg failed",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
