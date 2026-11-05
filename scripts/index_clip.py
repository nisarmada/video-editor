#!/usr/bin/env python3
"""
Merge per-clip index JSON files into one index/<clip>.json for planning.
Usage: python scripts/index_clip.py <video_path> [--force]
"""

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import (  # noqa: E402
    cache_hit,
    captions_path,
    keyframes_path,
    load_json,
    merged_index_path,
    save_json,
    silences_path,
    shots_path,
    transcript_path,
)
from media import clip_metadata  # noqa: E402
from probe import get_video_info  # noqa: E402


def require_file(path: Path, label: str) -> dict:
    data = load_json(path)
    if data is None:
        print(f"Error: missing {label} at {path}", file=sys.stderr)
        sys.exit(1)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Build merged clip index JSON")
    parser.add_argument("video_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_path = merged_index_path(video_path)
    if cache_hit(out_path, args.force):
        print(f"Using cached merged index: {out_path}")
        return

    transcript = require_file(transcript_path(video_path), "transcript")
    shots = require_file(shots_path(video_path), "shots")
    keyframes = require_file(keyframes_path(video_path), "keyframes")

    silences = load_json(silences_path(video_path))
    if silences is None:
        print("Note: no silences JSON; merged index will omit silences.")

    captions = load_json(captions_path(video_path))
    if captions is None:
        print("Note: no AI captions JSON; merged index will omit captions.")

    duration, has_audio, _rotation = clip_metadata(video_path)
    probe = get_video_info(video_path)
    video_stream = next(
        (s for s in probe.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )

    payload = {
        "clip": video_path.name,
        "source_path": str(video_path),
        "duration_seconds": round(duration, 3),
        "has_audio": has_audio,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "transcript": transcript,
        "shots": shots.get("shots", shots),
        "keyframes": keyframes.get("keyframes", keyframes),
    }
    if silences is not None:
        payload["silences"] = silences.get("silences", silences)
    if captions is not None:
        payload["captions"] = captions

    save_json(out_path, payload)
    print(f"Wrote merged index: {out_path}")
    print(
        f"  transcript segments: {len(transcript.get('segments', []))}  |  "
        f"shots: {len(payload['shots'])}  |  "
        f"keyframes: {len(payload['keyframes'])}"
    )


if __name__ == "__main__":
    main()
