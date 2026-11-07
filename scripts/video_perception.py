#!/usr/bin/env python3
"""
Local video perception per shot: palette, brightness, contrast, motion, shake,
optional face samples, and downscaled JPEGs for later vision input.

Usage: python scripts/video_perception.py <video_path> [--force]
Requires shots.py output. No API calls.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import (  # noqa: E402
    cache_hit,
    load_json,
    perception_dir,
    perception_path,
    save_json,
    shots_path,
)
from media import video_duration_seconds  # noqa: E402

VISION_LONG_EDGE = 512
VISION_FRAMES_PER_SHOT = 4
METRIC_SAMPLE_FRAMES = 10
PALETTE_COLORS = 5

_FACE_CASCADE: cv2.CascadeClassifier | None = None


def _face_cascade() -> cv2.CascadeClassifier | None:
    global _FACE_CASCADE
    if _FACE_CASCADE is not None:
        return _FACE_CASCADE
    path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not path.is_file():
        return None
    cascade = cv2.CascadeClassifier(str(path))
    if cascade.empty():
        return None
    _FACE_CASCADE = cascade
    return cascade


def sample_times(start: float, end: float, count: int) -> list[float]:
    """Evenly spaced sample times inside [start, end]."""
    start = float(start)
    end = float(end)
    if end <= start:
        return [start]
    if count <= 1:
        return [round((start + end) / 2, 4)]
    step = (end - start) / (count + 1)
    return [round(start + step * (i + 1), 4) for i in range(count)]


def read_bgr_frame(video_path: Path, time_sec: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_sec) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        return frame
    finally:
        cap.release()


def dominant_palette_rgb(frame_bgr: np.ndarray, k: int = PALETTE_COLORS) -> list[list[int]]:
    """Five main colors as [r,g,b] integers (0-255)."""
    small = cv2.resize(frame_bgr, (160, 90), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    if len(pixels) < k:
        k = max(1, len(pixels))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _compactness, labels, centers = cv2.kmeans(
        pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    flat = labels.flatten()
    counts = [(int(center_id), int(np.sum(flat == center_id))) for center_id in range(k)]
    counts.sort(key=lambda pair: pair[1], reverse=True)
    colors: list[list[int]] = []
    for center_id, _n in counts:
        b, g, r = centers[center_id]
        colors.append([int(round(r)), int(round(g)), int(round(b))])
    return colors[:k]


def luminance_stats(gray: np.ndarray) -> tuple[float, float]:
    """Mean brightness and contrast (std of luminance), each 0-1 scale."""
    g = gray.astype(np.float32) / 255.0
    return float(np.mean(g)), float(np.std(g))


def motion_level(frames_gray: list[np.ndarray]) -> float:
    """Mean absolute pixel difference between consecutive sampled frames (0-1)."""
    if len(frames_gray) < 2:
        return 0.0
    deltas: list[float] = []
    for a, b in zip(frames_gray, frames_gray[1:]):
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]))
        diff = cv2.absdiff(a, b)
        deltas.append(float(np.mean(diff)) / 255.0)
    return round(float(np.mean(deltas)), 6)


def shake_score(frames_gray: list[np.ndarray]) -> float:
    """
    Variability of frame-to-frame translation (0+). Constant pans score lower
    than irregular jitter when mean motion is similar.
    """
    if len(frames_gray) < 2:
        return 0.0
    h, w = frames_gray[0].shape[:2]
    diag = max(1.0, float(np.hypot(h, w)))
    norms: list[float] = []
    for a, b in zip(frames_gray, frames_gray[1:]):
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]))
        diff = cv2.absdiff(a, b)
        if float(np.mean(diff)) / 255.0 < 0.001:
            norms.append(0.0)
            continue
        shift, _ = cv2.phaseCorrelate(a.astype(np.float32), b.astype(np.float32))
        norms.append(float(np.hypot(shift[0], shift[1])) / diag)
    if not norms:
        return 0.0
    jitter = float(np.std(norms))
    drift = float(np.mean(norms))
    return round(jitter + 0.35 * drift, 6)


def faces_in_frame(frame_bgr: np.ndarray) -> int:
    cascade = _face_cascade()
    if cascade is None:
        return 0
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
    return int(len(faces))


def extract_vision_jpeg(
    video_path: Path,
    time_sec: float,
    out_jpg: Path,
    long_edge: int = VISION_LONG_EDGE,
) -> tuple[int, int]:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale='if(gt(iw,ih),{long_edge},-2):if(gt(iw,ih),-2,{long_edge})'"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{time_sec:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        scale,
        "-q:v",
        "4",
        str(out_jpg),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg vision frame failed")
    probe = cv2.imread(str(out_jpg))
    if probe is None:
        raise RuntimeError(f"Could not read written jpeg: {out_jpg}")
    h, w = probe.shape[:2]
    return w, h


def analyze_shot(
    video_path: Path,
    shot_index: int,
    start: float,
    end: float,
    frame_dir: Path,
) -> dict:
    metric_times = sample_times(start, end, METRIC_SAMPLE_FRAMES)
    vision_times = sample_times(start, end, VISION_FRAMES_PER_SHOT)

    grays: list[np.ndarray] = []
    palette: list[list[int]] | None = None
    brightness_vals: list[float] = []
    contrast_vals: list[float] = []
    face_hits = 0
    face_samples = 0

    for t in metric_times:
        bgr = read_bgr_frame(video_path, t)
        if bgr is None:
            continue
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (320, 180))
        grays.append(gray)
        mean_b, contrast = luminance_stats(gray)
        brightness_vals.append(mean_b)
        contrast_vals.append(contrast)
        if palette is None:
            palette = dominant_palette_rgb(bgr)
        n_faces = faces_in_frame(bgr)
        face_samples += 1
        if n_faces > 0:
            face_hits += 1

    vision_frames: list[dict] = []
    for j, t in enumerate(vision_times, start=1):
        rel = Path("index") / "perception" / video_path.stem / f"shot_{shot_index + 1:03d}_k{j:02d}.jpg"
        out = Path.cwd() / rel
        try:
            w, h = extract_vision_jpeg(video_path, t, out)
        except RuntimeError:
            continue
        vision_frames.append(
            {
                "time": round(t, 4),
                "path": str(rel).replace("\\", "/"),
                "width": w,
                "height": h,
            }
        )

    duration = round(max(0.0, end - start), 6)
    return {
        "shot_index": shot_index,
        "start": round(start, 4),
        "end": round(end, 4),
        "duration_seconds": duration,
        "palette_rgb": palette or [],
        "mean_brightness": round(float(np.mean(brightness_vals)), 4) if brightness_vals else None,
        "contrast": round(float(np.mean(contrast_vals)), 4) if contrast_vals else None,
        "motion_level": motion_level(grays),
        "shake_score": shake_score(grays),
        "face_samples": face_samples,
        "face_sample_hits": face_hits,
        "vision_frames": vision_frames,
    }


def build_video_perception(video_path: Path, *, force: bool = False) -> dict:
    video_path = video_path.resolve()
    out_path = perception_path(video_path)
    if cache_hit(out_path, force) and not force:
        data = load_json(out_path)
        if isinstance(data, dict):
            return data

    shots_doc = load_json(shots_path(video_path))
    if not isinstance(shots_doc, dict) or not shots_doc.get("shots"):
        raise RuntimeError(f"Run shots.py first ({shots_path(video_path)})")

    duration = video_duration_seconds(video_path)
    shots = shots_doc.get("shots") or []
    if not shots:
        shots = [{"start": 0.0, "end": duration}]

    frame_dir = perception_dir(video_path)
    t0 = time.perf_counter()
    analyzed: list[dict] = []
    for i, shot in enumerate(shots):
        start = float(shot["start"])
        end = float(shot["end"])
        print(f"Shot {i + 1}: perception {start:.2f}s–{end:.2f}s")
        analyzed.append(analyze_shot(video_path, i, start, end, frame_dir))

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    payload = {
        "clip": video_path.name,
        "duration_seconds": round(duration, 6),
        "version": 1,
        "vision_long_edge_px": VISION_LONG_EDGE,
        "shots": analyzed,
        "timing_ms": {"total": elapsed_ms},
    }
    save_json(out_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Local per-shot video perception")
    parser.add_argument("video_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_path = perception_path(video_path)
    if cache_hit(out_path, args.force) and not args.force:
        print(f"Using cached perception: {out_path}")
        return

    try:
        payload = build_video_perception(video_path, force=args.force)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Saved: {out_path}  ({len(payload.get('shots') or [])} shots)")
    print(f"  analyze time: {payload.get('timing_ms', {}).get('total')} ms")


if __name__ == "__main__":
    main()
