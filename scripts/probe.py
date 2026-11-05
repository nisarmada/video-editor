#!/usr/bin/env python3
"""
Print basic info about a video file using ffprobe (via subprocess).
Usage: python scripts/probe.py <path-to-video>
"""

import json
import subprocess
import sys
from pathlib import Path


def get_video_info(path: Path) -> dict:
    """Run ffprobe and return parsed JSON for the first video and audio streams."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "ffprobe failed (is FFmpeg installed?)"
        )
    return json.loads(result.stdout)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/probe.py <video-file>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = get_video_info(path)
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration = None
    if "format" in data and data["format"].get("duration"):
        duration = float(data["format"]["duration"])
    elif video and video.get("duration"):
        duration = float(video["duration"])

    if video is None:
        print("Error: no video stream found", file=sys.stderr)
        sys.exit(1)

    width = video.get("width", "?")
    height = video.get("height", "?")

    # Frame rate can be "30/1" or a number
    fps_raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/0"
    if "/" in str(fps_raw):
        num, den = fps_raw.split("/", 1)
        fps = float(num) / float(den) if float(den) else 0.0
    else:
        fps = float(fps_raw)

    print(f"duration_seconds: {duration if duration is not None else 'unknown'}")
    print(f"resolution: {width}x{height}")
    print(f"fps: {fps:.3f}")
    print(f"has_audio: {has_audio}")


if __name__ == "__main__":
    main()
