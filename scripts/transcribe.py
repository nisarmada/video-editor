#!/usr/bin/env python3
"""
Transcribe speech in a video clip with faster-whisper.
Usage: python scripts/transcribe.py <video_path>
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

# Reuse ffprobe helper to check for audio and read duration
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from index_cache import cache_hit, save_json, transcript_path  # noqa: E402
from probe import get_video_info  # noqa: E402


def has_audio_track(path: Path) -> bool:
    data = get_video_info(path)
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def video_duration_seconds(path: Path) -> float:
    data = get_video_info(path)
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        return float(fmt["duration"])
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and stream.get("duration"):
            return float(stream["duration"])
    return 0.0


def extract_audio_wav(video_path: Path, wav_path: Path) -> None:
    """Pull mono 16 kHz WAV from the video (Whisper's expected format)."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg audio extract failed")


def transcribe_wav(wav_path: Path) -> tuple[list[dict], str, float]:
    """
    Run faster-whisper (small model, CPU, int8) with word timestamps and VAD.
    Returns (segments, language, duration from model).
    """
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(wav_path),
        word_timestamps=True,
        vad_filter=True,
    )

    segments: list[dict] = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append(
                    {
                        "word": w.word.strip(),
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                    }
                )
        text = (seg.text or "").strip()
        if not text and not words:
            continue
        segments.append(
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": text,
                "words": words,
            }
        )

    language = info.language or "unknown"
    duration = float(info.duration or 0.0)
    return segments, language, duration


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a video clip")
    parser.add_argument("video_path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-transcribe even if index JSON already exists",
    )
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    duration = video_duration_seconds(video_path)
    out_path = transcript_path(video_path)

    if cache_hit(out_path, args.force):
        print(f"Using cached transcript: {out_path}")
        import json

        data = json.loads(out_path.read_text())
        for seg in data.get("segments") or []:
            print(f"[{seg['start']:.2f} -> {seg['end']:.2f}] {seg['text']}")
        return

    if not has_audio_track(video_path):
        payload = {
            "clip": video_path.name,
            "language": None,
            "duration_seconds": round(duration, 3),
            "segments": [],
        }
        save_json(out_path, payload)
        print(f"No audio track in {video_path.name}; saved empty transcript to {out_path}")
        sys.exit(0)

    print("Extracting audio with ffmpeg...")
    wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = Path(wav_file.name)
    wav_file.close()

    try:
        extract_audio_wav(video_path, wav_path)
        print("Transcribing (first run downloads the small model; may take a while)...")
        segments, language, model_duration = transcribe_wav(wav_path)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        wav_path.unlink(missing_ok=True)

    total_duration = duration if duration > 0 else model_duration

    if not segments:
        payload = {
            "clip": video_path.name,
            "language": language,
            "duration_seconds": round(total_duration, 3),
            "segments": [],
        }
        save_json(out_path, payload)
        print(f"No speech detected in {video_path.name}; saved empty transcript to {out_path}")
        sys.exit(0)

    payload = {
        "clip": video_path.name,
        "language": language,
        "duration_seconds": round(total_duration, 3),
        "segments": segments,
    }
    save_json(out_path, payload)

    print(f"\nLanguage: {language}  |  Saved: {out_path}\n")
    for seg in segments:
        print(f"[{seg['start']:.2f} -> {seg['end']:.2f}] {seg['text']}")


if __name__ == "__main__":
    main()
