"""
Shared FFmpeg helpers: probe metadata, cut, join, and render timeline plans.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

TARGET_W, TARGET_H, FPS = 1080, 1920, 30
AUDIO_FADE_SECONDS = 0.02


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


def video_duration_seconds(path: Path) -> float:
    data = ffprobe_json(path)
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        return float(fmt["duration"])
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and stream.get("duration"):
            return float(stream["duration"])
    raise RuntimeError(f"Could not determine duration for {path}")


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


def normalize_video_chain(rotation: int | None, label_in: str, label_out: str) -> str:
    rot = rotation_filter(rotation)
    return (
        f"{label_in}{rot}"
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={FPS},format=yuv420p{label_out}"
    )


def run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def cut_segment(
    input_path: Path,
    start: float,
    end: float,
    output_path: Path,
) -> None:
    """Re-encode one segment (frame-accurate H.264 + AAC)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
    run_ffmpeg(cmd)


def build_join_filter_graph(inputs: list[Path]) -> tuple[str, list[str]]:
    """Normalize whole files, then concat (used by join.py)."""
    meta = [clip_metadata(p) for p in inputs]
    parts: list[str] = []
    ffmpeg_inputs: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []

    for i, path in enumerate(inputs):
        duration, has_audio, rotation = meta[i]
        ffmpeg_inputs.extend(["-i", str(path)])
        parts.append(
            normalize_video_chain(rotation, f"[{i}:v]", f"[v{i}]")
        )
        vlabels.append(f"[v{i}]")
        if has_audio:
            parts.append(
                f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]"
            )
        else:
            parts.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={duration:.6f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        alabels.append(f"[a{i}]")

    n = len(inputs)
    parts.append(f"{''.join(vlabels)}concat=n={n}:v=1:a=0[vout]")
    parts.append(f"{''.join(alabels)}concat=n={n}:v=0:a=1[aout]")
    return ";".join(parts), ffmpeg_inputs


def join_files(input_paths: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex, ffmpeg_inputs = build_join_filter_graph(input_paths)
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
    run_ffmpeg(cmd)


def build_timeline_filter_graph(
    segments: list[tuple[Path, float, float]],
) -> tuple[str, list[str]]:
    """
    Each item is (source_path, start_sec, end_sec).
    Trims, normalizes, applies short audio fades at cuts, then concats.
    """
    parts: list[str] = []
    ffmpeg_inputs: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []

    path_to_index: dict[Path, int] = {}
    meta_cache: dict[Path, tuple[float, bool, int | None]] = {}

    for path, _start, _end in segments:
        resolved = path.resolve()
        if resolved not in path_to_index:
            path_to_index[resolved] = len(path_to_index)
            ffmpeg_inputs.extend(["-i", str(resolved)])
            meta_cache[resolved] = clip_metadata(resolved)

    n = len(segments)
    for i, (path, start, end) in enumerate(segments):
        idx = path_to_index[path.resolve()]
        duration, has_audio, rotation = meta_cache[path.resolve()]
        seg_len = max(end - start, 0.001)

        rot = rotation_filter(rotation)
        parts.append(
            f"[{idx}:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"{rot}"
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,fps={FPS},format=yuv420p[v{i}]"
        )
        vlabels.append(f"[v{i}]")

        audio_filters = [
            f"atrim=start={start:.6f}:end={end:.6f}",
            "asetpts=PTS-STARTPTS",
            "aformat=sample_rates=44100:channel_layouts=stereo",
        ]
        if i > 0:
            audio_filters.append(f"afade=t=in:st=0:d={AUDIO_FADE_SECONDS}")
        if i < n - 1:
            fade_out_st = max(seg_len - AUDIO_FADE_SECONDS, 0)
            audio_filters.append(
                f"afade=t=out:st={fade_out_st:.6f}:d={AUDIO_FADE_SECONDS}"
            )

        if has_audio:
            chain = ",".join(audio_filters)
            parts.append(f"[{idx}:a]{chain}[a{i}]")
        else:
            parts.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={seg_len:.6f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        alabels.append(f"[a{i}]")

    parts.append(f"{''.join(vlabels)}concat=n={n}:v=1:a=0[vout]")
    parts.append(f"{''.join(alabels)}concat=n={n}:v=0:a=1[aout]")
    return ";".join(parts), ffmpeg_inputs


def render_timeline(segments: list[tuple[Path, float, float]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex, ffmpeg_inputs = build_timeline_filter_graph(segments)
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
    run_ffmpeg(cmd)
