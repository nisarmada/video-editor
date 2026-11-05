#!/usr/bin/env python3
"""
Join multiple clips into one vertical 1080x1920 @ 30fps video.
Usage: python scripts/join.py <output> <input1> <input2> [more inputs...]
"""

import json
import subprocess
import sys
from pathlib import Path


def ffprobe_json(path: Path) -> dict:
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
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout)


def clip_metadata(path: Path) -> tuple[float, bool, int | None]:
    """Duration (seconds), has_audio, rotation in degrees if present."""
    data = ffprobe_json(path)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and s.get("duration"):
                duration = float(s["duration"])
                break
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    rotation = None
    for s in data.get("streams", []):
        if s.get("codec_type") != "video":
            continue
        for side in s.get("side_data_list") or []:
            if side.get("rotation") is not None:
                rotation = int(side["rotation"])
                break
    return duration, has_audio, rotation


def rotation_filter(degrees: int | None) -> str:
    """vf prefix to fix phone rotation metadata before scale/pad."""
    if degrees is None or degrees == 0:
        return ""
    d = degrees % 360
    if d in (90, -270):
        return "transpose=1,"
    if d in (270, -90):
        return "transpose=2,"
    if d in (180, -180):
        return "transpose=1,transpose=1,"
    return ""


def build_filter_graph(
    inputs: list[Path],
) -> tuple[str, list[str]]:
    """Normalize each clip, then concat. Returns filter_complex and ffmpeg -i args."""
    meta = [clip_metadata(p) for p in inputs]
    parts: list[str] = []
    ffmpeg_inputs: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []

    target_w, target_h = 1080, 1920

    for i, path in enumerate(inputs):
        duration, has_audio, rotation = meta[i]
        ffmpeg_inputs.extend(["-i", str(path)])
        rot = rotation_filter(rotation)
        parts.append(
            f"[{i}:v]{rot}"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,fps=30,format=yuv420p[v{i}]"
        )
        vlabels.append(f"[v{i}]")

        if has_audio:
            parts.append(
                f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]"
            )
        else:
            # Silent track matched to this clip's length
            parts.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={duration:.6f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        alabels.append(f"[a{i}]")

    n = len(inputs)
    parts.append(f"{''.join(vlabels)}concat=n={n}:v=1:a=0[vout]")
    parts.append(f"{''.join(alabels)}concat=n={n}:v=0:a=1[aout]")
    return ";".join(parts), ffmpeg_inputs


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python scripts/join.py <output> <input1> <input2> [more...]",
            file=sys.stderr,
        )
        sys.exit(1)

    output_path = Path(sys.argv[1])
    input_paths = [Path(p) for p in sys.argv[2:]]

    for p in input_paths:
        if not p.is_file():
            print(f"Error: input file not found: {p}", file=sys.stderr)
            sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        filter_complex, ffmpeg_inputs = build_filter_graph(input_paths)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    cmd = [
        "ffmpeg",
        "-y",
        *ffmpeg_inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
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
    print("Running ffmpeg (re-encode; this can take a while)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or "ffmpeg failed", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
