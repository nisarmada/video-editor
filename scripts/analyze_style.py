#!/usr/bin/env python3
"""
Analyze a reference video and write a style profile JSON for the AI planner.

Uses PySceneDetect (cuts), OpenCV (frame sampling), faster-whisper (speech density),
and Claude Vision (editing mood / aesthetics).

Usage:
  python scripts/analyze_style.py references/my_ref.mp4 --name fast_vlog --out plans/styles/fast_vlog.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from media import clip_metadata  # noqa: E402
from style_profile import slug_style_id  # noqa: E402
from transcribe import extract_audio_wav, transcribe_wav  # noqa: E402

VISION_SYSTEM = """You analyze reference vertical/social videos for automated editing.
Return ONLY valid JSON (no markdown) with this shape:
{
  "editing_mood": "<short phrase>",
  "text_overlay_placement": "<e.g. lower third, centered top, minimal>",
  "zoom_style": "<e.g. static, punch-in on beats, Ken Burns>",
  "pacing_feel": "<e.g. frantic, calm, steady hook then accelerates>",
  "visual_aesthetic_notes": "<one or two sentences>",
  "suggested_planner_rules": [
    "<imperative rule the planner should follow when imitating this style>",
    "<another rule>"
  ]
}
Be concrete and tied to what you see in the frames (composition, face size, graphics).
"""


def _duration_seconds(path: Path) -> float:
    d, _a, _r = clip_metadata(path)
    return float(d) if d and d > 0 else 0.0


def detect_shot_lengths(video_path: Path, threshold: float) -> tuple[list[dict], int]:
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold))
    manager.detect_scenes(video)
    scene_list = manager.get_scene_list()
    shots: list[dict] = []
    for start_tc, end_tc in scene_list:
        shots.append(
            {
                "start": round(start_tc.seconds, 3),
                "end": round(end_tc.seconds, 3),
            }
        )
    # Count transitions between scenes as "hard cuts" (inside one continuous file)
    cut_count = max(0, len(shots) - 1) if shots else 0
    return shots, cut_count


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def sample_frame_jpegs(
    video_path: Path, times: list[float], max_dim: int = 720
) -> list[tuple[float, bytes]]:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video_path}")
    out: list[tuple[float, bytes]] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            scale = min(1.0, max_dim / max(w, h))
            if scale < 1.0:
                frame = cv2.resize(
                    frame,
                    (int(w * scale), int(h * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            ok2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok2:
                out.append((t, buf.tobytes()))
    finally:
        cap.release()
    return out


def speech_metrics(video_path: Path) -> dict[str, float | int]:
    """Words per minute, speech ratio, rough caption-speech alignment proxy."""
    duration = _duration_seconds(video_path)
    if duration <= 0:
        return {
            "word_count": 0,
            "words_per_minute": 0.0,
            "speech_time_estimate_seconds": 0.0,
            "speech_density": 0.0,
        }
    with tempfile.TemporaryDirectory(prefix="ref_style_") as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_audio_wav(video_path, wav)
        segments, _lang, _dur = transcribe_wav(wav)

    word_count = 0
    speech_span = 0.0
    for seg in segments:
        words = seg.get("words") or []
        word_count += len(words)
        if words:
            speech_span += max(
                0.0, float(words[-1].get("end", 0)) - float(words[0].get("start", 0))
            )
        else:
            speech_span += max(
                0.0, float(seg.get("end", 0)) - float(seg.get("start", 0))
            )

    wpm = (word_count / duration) * 60.0 if duration > 0 else 0.0
    density = min(1.0, speech_span / duration) if duration > 0 else 0.0
    return {
        "word_count": word_count,
        "words_per_minute": round(wpm, 2),
        "speech_time_estimate_seconds": round(speech_span, 2),
        "speech_density": round(density, 3),
    }


def call_claude_vision(
    frames: list[tuple[float, bytes]],
    *,
    api_key: str | None,
    model: str,
) -> dict:
    import anthropic

    key = (api_key or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=key)
    blocks: list[dict] = []
    for t_sec, raw in frames:
        b64 = base64.standard_b64encode(raw).decode("ascii")
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            }
        )
        blocks.append(
            {
                "type": "text",
                "text": f"Frame at t={t_sec:.2f}s",
            }
        )
    blocks.append(
        {
            "type": "text",
            "text": (
                f"You are given {len(frames)} frames in order from one reference edit. "
                + VISION_SYSTEM
            ),
        }
    )
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": blocks}],
    )
    parts = [b.text for b in response.content if b.type == "text"]
    text = "\n".join(parts).strip()
    fence_start = text.find("{")
    fence_end = text.rfind("}")
    if fence_start >= 0 and fence_end > fence_start:
        text = text[fence_start : fence_end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Vision model did not return a JSON object")
    return data


def analyze_reference_video(
    video_path: Path,
    *,
    style_id: str,
    style_name: str,
    sc_threshold: float = 27.0,
    vision_model: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Build full style profile dict (caller writes JSON)."""
    video_path = video_path.resolve()
    if not video_path.is_file():
        raise FileNotFoundError(video_path)

    duration = _duration_seconds(video_path)
    shots, cut_count = detect_shot_lengths(video_path, sc_threshold)
    lengths = [max(1e-6, s["end"] - s["start"]) for s in shots]
    sl_sorted = sorted(lengths)
    cpm = (cut_count / duration) * 60.0 if duration > 0 else 0.0

    cuts_block = {
        "shot_count": len(shots),
        "hard_cut_count": cut_count,
        "cuts_per_minute": round(cpm, 2),
        "shot_length_seconds": {
            "mean": round(statistics.mean(lengths), 3) if lengths else 0.0,
            "min": round(min(lengths), 3) if lengths else 0.0,
            "max": round(max(lengths), 3) if lengths else 0.0,
            "p25": round(percentile(sl_sorted, 0.25), 3) if sl_sorted else 0.0,
            "p75": round(percentile(sl_sorted, 0.75), 3) if sl_sorted else 0.0,
        },
        "dominant_transition": "hard_cut",
    }

    speech = speech_metrics(video_path)

    # Sample 6–8 frames across the timeline
    n = 8
    if duration <= 0:
        times = [0.0]
    else:
        times = [duration * (i + 0.5) / n for i in range(n)]
    frame_data = sample_frame_jpegs(video_path, times)
    if len(frame_data) < 2:
        raise RuntimeError(
            "Could not decode enough frames from the reference (try re-encoding with ffmpeg)."
        )

    vm = vision_model or os.environ.get(
        "ANTHROPIC_STYLE_VISION_MODEL", "claude-haiku-4-5-20251001"
    )
    vision = call_claude_vision(frame_data, api_key=api_key, model=vm)

    suggested = vision.get("suggested_planner_rules") or []
    if not isinstance(suggested, list):
        suggested = [str(suggested)]

    # Quantitative imitate rules (planner can parse these)
    sl = cuts_block["shot_length_seconds"]
    quant_rules = [
        (
            f"When imitating this style, prefer shot durations roughly "
            f"{sl['p25']:.1f}s–{sl['p75']:.1f}s (reference p25–p75), "
            f"and avoid much longer than {sl['max']:.1f}s unless the brief demands it."
        ),
        (
            f"Target cut rhythm near {cuts_block['cuts_per_minute']:.1f} cuts per minute "
            f"when it fits the brief (reference had {cuts_block['hard_cut_count']} hard cuts "
            f"in {duration:.1f}s)."
        ),
        (
            f"Speech density reference: ~{speech['words_per_minute']:.0f} words/minute "
            f"and on-screen pacing that matches that density when using talking-head sources."
        ),
    ]

    profile = {
        "schema_version": 1,
        "style_id": style_id,
        "style_name": style_name,
        "source_video": str(video_path),
        "duration_seconds": round(duration, 3),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cuts": cuts_block,
        "speech": speech,
        "visual_aesthetics": {
            "editing_mood": vision.get("editing_mood", ""),
            "text_overlay_placement": vision.get("text_overlay_placement", ""),
            "zoom_style": vision.get("zoom_style", ""),
            "pacing_feel": vision.get("pacing_feel", ""),
            "notes": vision.get("visual_aesthetic_notes", ""),
        },
        "planner_constraints": {
            "imitate": quant_rules + [str(x) for x in suggested if str(x).strip()],
            "avoid": [],
        },
    }
    return profile


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Analyze a reference video into a style profile")
    parser.add_argument("video_path", type=Path)
    parser.add_argument("--name", required=True, help="style_name field (display)")
    parser.add_argument("--id", dest="style_id", help="style_id slug (default: slug from --name)")
    parser.add_argument("--out", type=Path, help="Output JSON path (default: plans/styles/<id>.json)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=27.0,
        help="PySceneDetect ContentDetector threshold (same family as shots.py)",
    )
    args = parser.parse_args()

    style_id = slug_style_id(args.style_id or args.name)
    out_path = args.out or Path("plans") / "styles" / f"{style_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        profile = analyze_reference_video(
            args.video_path,
            style_id=style_id,
            style_name=args.name.strip(),
            sc_threshold=args.threshold,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    out_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote style profile: {out_path}")


if __name__ == "__main__":
    main()
