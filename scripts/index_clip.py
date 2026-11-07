#!/usr/bin/env python3
"""
Merge per-clip index JSON files into one index/<clip>.json for planning.
Usage: python scripts/index_clip.py <media_path> [--force]

Works for video (with or without audio) and audio-only files; optional analyses
are merged when present (missing = omitted unless noted).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from footage_exts import AUDIO_EXTS, VIDEO_EXTS  # noqa: E402
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


def build_merged_index(clip_path: Path, *, force: bool = False) -> dict:
    """
    Build merged index dict for one footage file. Does not require shots/keyframes
    for audio-only; video without transcript still merges other fields.
    """
    clip_path = clip_path.resolve()
    out_path = merged_index_path(clip_path)
    if cache_hit(out_path, force) and not force:
        data = load_json(out_path)
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"Corrupt merged index: {out_path}")

    ext = clip_path.suffix.lower()
    is_audio_only = ext in AUDIO_EXTS
    is_video = ext in VIDEO_EXTS

    transcript = load_json(transcript_path(clip_path)) or {}
    silences_doc = load_json(silences_path(clip_path))
    silences = None
    if isinstance(silences_doc, dict):
        silences = silences_doc.get("silences", silences_doc)

    shots_doc = load_json(shots_path(clip_path))
    shots: list = []
    if isinstance(shots_doc, dict):
        shots = shots_doc.get("shots") or []

    keyframes_doc = load_json(keyframes_path(clip_path))
    keyframes: list = []
    if isinstance(keyframes_doc, dict):
        keyframes = keyframes_doc.get("keyframes") or []

    captions = load_json(captions_path(clip_path))

    duration, has_audio, rotation = clip_metadata(clip_path)

    width: int | None = None
    height: int | None = None
    if is_video:
        try:
            probe = get_video_info(clip_path)
            video_stream = next(
                (s for s in probe.get("streams", []) if s.get("codec_type") == "video"),
                {},
            )
            width = video_stream.get("width")
            height = video_stream.get("height")
        except (OSError, RuntimeError):
            pass

    payload: dict = {
        "clip": clip_path.name,
        "source_path": str(clip_path),
        "kind": "audio" if is_audio_only else "video",
        "duration_seconds": round(float(duration), 6),
        "has_video": is_video,
        "has_audio": bool(has_audio),
        "rotation_degrees": rotation,
        "transcript": transcript,
    }
    if is_video:
        payload["width"] = width
        payload["height"] = height
    if silences is not None:
        payload["silences"] = silences
    if is_video:
        payload["shots"] = shots
        payload["keyframes"] = keyframes
    if is_video and captions is not None:
        payload["captions"] = captions

    save_json(out_path, payload)
    return payload


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
    if cache_hit(out_path, args.force) and not args.force:
        print(f"Using cached merged index: {out_path}")
        return

    try:
        payload = build_merged_index(video_path, force=args.force)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote merged index: {out_path}")
    transcript = payload.get("transcript") or {}
    cap = payload.get("captions") or {}
    cap_count = len(cap.get("frames", [])) if isinstance(cap, dict) else 0
    print(
        f"  transcript segments: {len(transcript.get('segments', []))}  |  "
        f"shots: {len(payload.get('shots') or [])}  |  "
        f"keyframes: {len(payload.get('keyframes') or [])}  |  "
        f"AI frame captions: {cap_count}"
    )


if __name__ == "__main__":
    main()
