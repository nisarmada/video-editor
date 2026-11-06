"""
Shared FFmpeg helpers: probe metadata, cut, join, and render timeline plans.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

TARGET_W, TARGET_H, FPS = 1080, 1920, 30
AUDIO_FADE_SECONDS = 0.02


@dataclass(frozen=True)
class TimelinePiece:
    """One concat unit: file trim (or gap), with optional speed / volume / zoom."""

    path: Path | None
    source_start: float
    source_end: float
    speed: float = 1.0
    volume: float = 1.0
    zoom: float | None = None

    def is_gap(self) -> bool:
        return self.path is None

    def source_span(self) -> float:
        return max(self.source_end - self.source_start, 0.001)

    def output_duration(self) -> float:
        """Wall-clock duration on the output timeline (matches preview)."""
        if self.is_gap():
            return self.source_span()
        return self.source_span() / self.effective_speed()

    def effective_speed(self) -> float:
        s = float(self.speed)
        return s if s > 0 else 1.0


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


def run_ffmpeg_with_progress(
    cmd: list[str],
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float | None], None] | None = None,
) -> None:
    """
    Run ffmpeg with -progress to a temp file; parse out_time_ms vs duration for percent.
    """
    if len(cmd) < 2 or cmd[0] != "ffmpeg":
        raise ValueError("Expected ffmpeg command")

    fd, prog_tmp = tempfile.mkstemp(suffix="_ffprogress.txt")
    os.close(fd)
    prog_path = Path(prog_tmp)

    try:
        # Insert -progress and -nostats before the final output argument
        out_arg = cmd[-1]
        core = cmd[:-1] + ["-progress", str(prog_path), "-nostats", out_arg]

        proc = subprocess.Popen(
            core,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        duration_sec: float | None = None
        stderr_chunks: list[str] = []

        def pump_stderr() -> None:
            if proc.stderr:
                for line in proc.stderr:
                    stderr_chunks.append(line)

        err_t = threading.Thread(target=pump_stderr, daemon=True)
        err_t.start()

        def parse_progress_file() -> tuple[float | None, float | None]:
            nonlocal duration_sec
            try:
                raw = prog_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None, duration_sec
            dur_m = re.search(r"^duration=(\d+(?:\.\d+)?)\s*$", raw, re.MULTILINE)
            if dur_m:
                try:
                    duration_sec = float(dur_m.group(1))
                except ValueError:
                    pass
            time_m = None
            for m in re.finditer(r"^out_time_ms=(\d+)\s*$", raw, re.MULTILINE):
                time_m = m
            if not time_m:
                return None, duration_sec
            try:
                ms = float(time_m.group(1))
            except ValueError:
                return None, duration_sec
            return ms / 1_000_000.0, duration_sec

        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RuntimeError("Render cancelled")

            code = proc.poll()
            t_sec, dur = parse_progress_file()
            pct: float | None = None
            if dur is not None and dur > 1e-6 and t_sec is not None:
                pct = max(0.0, min(100.0, (t_sec / dur) * 100.0))
            elif on_progress:
                pct = None
            if on_progress:
                on_progress(pct)

            if code is not None:
                break
            time.sleep(0.25)

        err_t.join(timeout=2)
        if proc.returncode != 0:
            err_tail = "".join(stderr_chunks)[-4000:].strip()
            raise RuntimeError(err_tail or "ffmpeg failed")
    finally:
        prog_path.unlink(missing_ok=True)


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


def _atempo_chain_factors(speed: float) -> list[float]:
    """Split speed into atempo factors in (0.5, 2.0] per filter."""
    if speed <= 0:
        return []
    factors: list[float] = []
    remaining = float(speed)
    while remaining > 2.0 + 1e-9:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5 - 1e-9:
        factors.append(0.5)
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-6:
        factors.append(remaining)
    return factors


def _volume_filter_expr(volume: float) -> str:
    """Linear gain; clamp non-positive to silence."""
    v = float(volume)
    if v <= 0:
        return "volume=0"
    if abs(v - 1.0) < 1e-9:
        return "volume=1"
    return f"volume={v:.8f}"


def _zoom_punch_filter(zoom: float) -> str:
    """
    After 1080x1920 normalize: crop centered (1/zoom) fraction, scale back to frame.
    zoom 1.0 = no-op; zoom > 1 punch in.
    """
    z = float(zoom)
    if z <= 1.001:
        return ""
    # iw/ih are normalized frame dimensions (TARGET_W x TARGET_H)
    return (
        f"crop=w=iw/{z}:h=ih/{z}:x=(iw-iw/{z})/2:y=(ih-ih/{z})/2,"
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black"
    )


def build_timeline_filter_graph(
    pieces: list[TimelinePiece],
) -> tuple[str, list[str]]:
    """
    Trim each piece, normalize to 1080x1920 @ 30fps, optional zoom punch-in,
    speed via setpts / atempo (timeline duration matches preview), volume on audio.
    Gaps: lavfi black + silence.
    """
    parts: list[str] = []
    ffmpeg_inputs: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []

    path_to_index: dict[Path, int] = {}
    meta_cache: dict[Path, tuple[float, bool, int | None]] = {}
    next_input = 0

    n = len(pieces)
    for i, piece in enumerate(pieces):
        seg_out = piece.output_duration()

        if piece.is_gap():
            ffmpeg_inputs.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={TARGET_W}x{TARGET_H}:r={FPS}:d={seg_out:.6f}",
                ]
            )
            v_in = next_input
            next_input += 1
            ffmpeg_inputs.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r=44100:cl=stereo,atrim=duration={seg_out:.6f},"
                    f"asetpts=PTS-STARTPTS",
                ]
            )
            a_in = next_input
            next_input += 1
            parts.append(
                f"[{v_in}:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
                f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1,fps={FPS},format=yuv420p[v{i}]"
            )
            vlabels.append(f"[v{i}]")

            audio_filters = ["aformat=sample_rates=44100:channel_layouts=stereo"]
            if i > 0:
                audio_filters.insert(0, f"afade=t=in:st=0:d={AUDIO_FADE_SECONDS}")
            if i < n - 1:
                fade_out_st = max(seg_out - AUDIO_FADE_SECONDS, 0)
                audio_filters.append(
                    f"afade=t=out:st={fade_out_st:.6f}:d={AUDIO_FADE_SECONDS}"
                )
            parts.append(f"[{a_in}:a]{','.join(audio_filters)}[a{i}]")
            alabels.append(f"[a{i}]")
            continue

        path = piece.path
        assert path is not None
        resolved = path.resolve()
        if resolved not in path_to_index:
            path_to_index[resolved] = next_input
            ffmpeg_inputs.extend(["-i", str(resolved)])
            meta_cache[resolved] = clip_metadata(resolved)
            next_input += 1
        idx = path_to_index[resolved]
        _duration, has_audio, rotation = meta_cache[resolved]

        start = piece.source_start
        end = piece.source_end
        speed = piece.effective_speed()
        sp = f"{speed:.8f}".rstrip("0").rstrip(".") if speed != 1.0 else "1"

        rot = rotation_filter(rotation)
        v_after_norm = f"vn{i}"
        base_chain = (
            f"[{idx}:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"{rot}"
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,fps={FPS},format=yuv420p[{v_after_norm}]"
        )
        parts.append(base_chain)

        zoom_chain = _zoom_punch_filter(piece.zoom or 1.0)
        if zoom_chain:
            v_pre_speed = f"vz{i}"
            parts.append(f"[{v_after_norm}]{zoom_chain}[{v_pre_speed}]")
        else:
            v_pre_speed = v_after_norm

        # setpts after geometry so duration scales (faster = shorter clip on timeline)
        if abs(speed - 1.0) > 1e-6:
            parts.append(f"[{v_pre_speed}]setpts=PTS/{sp}[pre{i}]")
            vlabels.append(f"[pre{i}]")
        else:
            vlabels.append(f"[{v_pre_speed}]")

        tail_audio: list[str] = []
        for fac in _atempo_chain_factors(speed):
            tail_audio.append(f"atempo={fac:.8f}".rstrip("0").rstrip("."))
        tail_audio.append(_volume_filter_expr(piece.volume))
        tail_audio.append("aformat=sample_rates=44100:channel_layouts=stereo")

        if i > 0:
            tail_audio.append(f"afade=t=in:st=0:d={AUDIO_FADE_SECONDS}")
        if i < n - 1:
            fade_out_st = max(seg_out - AUDIO_FADE_SECONDS, 0)
            tail_audio.append(
                f"afade=t=out:st={fade_out_st:.6f}:d={AUDIO_FADE_SECONDS}"
            )
        tail_s = ",".join(tail_audio)

        if has_audio:
            head = f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS"
            parts.append(f"[{idx}:a]{head},{tail_s}[a{i}]")
        else:
            parts.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={seg_out:.6f},"
                f"asetpts=PTS-STARTPTS,{tail_s}[a{i}]"
            )
        alabels.append(f"[a{i}]")

    parts.append(f"{''.join(vlabels)}concat=n={n}:v=1:a=0[vout]")
    parts.append(f"{''.join(alabels)}concat=n={n}:v=0:a=1[aout]")
    return ";".join(parts), ffmpeg_inputs


def _ffmpeg_supports_filter(name: str) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-filters"],
        capture_output=True,
        text=True,
    )
    return name in result.stdout


def ffmpeg_has_libass() -> bool:
    """True if subtitles filter is available (libass)."""
    return _ffmpeg_supports_filter("subtitles")


def _escape_subtitles_path(p: Path) -> str:
    """Path segment for subtitles= filter (POSIX slashes; escape :, ', comma)."""
    s = str(p.resolve()).replace("\\", "/")
    return s.replace("\\", "/").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def burn_captions(
    input_video: Path,
    output_path: Path,
    caption_events: list[dict],
    ass_path: Path | None = None,
    fonts_dir: Path | None = None,
) -> None:
    """
    Burn captions onto video. Prefers libass (subtitles filter) with fontsdir when available.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if ass_path and ass_path.is_file() and ffmpeg_has_libass():
        tmp = Path(tempfile.mkstemp(suffix=".ass")[1])
        try:
            shutil.copy2(ass_path, tmp)
            sub_arg = _escape_subtitles_path(tmp)
            if fonts_dir is not None and fonts_dir.is_dir():
                fd = _escape_subtitles_path(fonts_dir)
                vf = f"subtitles={sub_arg}:fontsdir={fd}"
            else:
                vf = f"subtitles={sub_arg}"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(input_video),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-c:a",
                "copy",
                str(output_path),
            ]
            run_ffmpeg(cmd)
            return
        finally:
            tmp.unlink(missing_ok=True)

    _burn_captions_png_overlay(input_video, output_path, caption_events)


def _burn_captions_png_overlay(
    input_video: Path,
    output_path: Path,
    events: list[dict],
) -> None:
    """Fallback when ffmpeg lacks libass/drawtext (common on minimal Homebrew builds)."""
    from PIL import Image, ImageDraw, ImageFont

    from captions import FONT_SIZE, HIGHLIGHT_COLOUR, MARGIN_V, PLAY_RES_X, PLAY_RES_Y, PRIMARY_COLOUR  # noqa: WPS433

    if not events:
        shutil.copy2(input_video, output_path)
        return

    font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    font = ImageFont.truetype(font_path, FONT_SIZE)

    def ass_bgr_to_rgb(ass_hex: str) -> tuple[int, int, int]:
        hex_clean = ass_hex.replace("&H", "").replace("&", "")[:6]
        b = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        r = int(hex_clean[4:6], 16)
        return (r, g, b)

    primary = ass_bgr_to_rgb(PRIMARY_COLOUR)
    highlight = ass_bgr_to_rgb(HIGHLIGHT_COLOUR)

    tmp_dir = Path(tempfile.mkdtemp())
    png_paths: list[Path] = []
    try:
        for i, event in enumerate(events):
            img = Image.new("RGBA", (PLAY_RES_X, PLAY_RES_Y), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # chunk is already trimmed to spoken-so-far (see captions.visible_words)
            chunk = event["chunk"]
            active = event["active"]
            pieces = [(w["word"], w is active) for w in chunk]
            total_w = sum(
                draw.textlength(word + " ", font=font) for word, _ in pieces
            )
            x = (PLAY_RES_X - total_w) / 2
            y = PLAY_RES_Y - MARGIN_V
            for word, is_active in pieces:
                color = highlight if is_active else primary
                draw.text((x, y), word + " ", font=font, fill=(*color, 255))
                x += draw.textlength(word + " ", font=font)
            png = tmp_dir / f"cap_{i:04d}.png"
            img.save(png)
            png_paths.append(png)

        video_duration = clip_metadata(input_video)[0]
        cmd = ["ffmpeg", "-y", "-i", str(input_video)]
        for png in png_paths:
            cmd.extend(
                ["-loop", "1", "-t", f"{video_duration:.3f}", "-i", str(png)]
            )
        parts_fc: list[str] = []
        last = "[0:v]"
        for i, event in enumerate(events):
            out = f"[v{i + 1}]"
            t0 = event["start"]
            t1 = event["end"]
            parts_fc.append(
                f"{last}[{i + 1}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'{out}"
            )
            last = out
        filter_complex = ";".join(parts_fc)
        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                last,
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-c:a",
                "copy",
                str(output_path),
            ]
        )
        run_ffmpeg(cmd)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def render_timeline(
    pieces: list[TimelinePiece],
    output_path: Path,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float | None], None] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex, ffmpeg_inputs = build_timeline_filter_graph(pieces)
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
    if on_progress is not None or cancel_event is not None:
        run_ffmpeg_with_progress(
            cmd, cancel_event=cancel_event, on_progress=on_progress
        )
    else:
        run_ffmpeg(cmd)
