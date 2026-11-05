#!/usr/bin/env python3
"""
Build a keep-list timeline by removing long silences (and optional filler words).
Usage: python scripts/tighten_plan.py <video_path> [--remove-fillers]
"""

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import load_json, silences_path, transcript_path  # noqa: E402
from media import video_duration_seconds  # noqa: E402

# Edit this list to tune filler removal
FILLER_WORDS = [
    "um",
    "uh",
    "uhh",
    "umm",
    "like",
    "you know",
    "i mean",
    "sort of",
    "kind of",
]

SILENCE_REMOVE_MIN = 0.4
SPEECH_PADDING = 0.15
MERGE_GAP = 0.12


def normalize_word(text: str) -> str:
    return re.sub(r"[^\w\s']", "", text.lower()).strip()


def collect_filler_intervals(transcript: dict) -> list[tuple[float, float]]:
    """Return time ranges to cut based on filler word timestamps."""
    intervals: list[tuple[float, float]] = []
    segments = transcript.get("segments") or []

    for seg in segments:
        words = seg.get("words") or []
        if not words:
            continue
        i = 0
        while i < len(words):
            matched = False
            for phrase in sorted(FILLER_WORDS, key=len, reverse=True):
                parts = phrase.split()
                chunk = words[i : i + len(parts)]
                if len(chunk) != len(parts):
                    continue
                spoken = " ".join(normalize_word(w.get("word", "")) for w in chunk)
                if spoken == phrase:
                    start = float(chunk[0]["start"])
                    end = float(chunk[-1]["end"])
                    intervals.append((start, end))
                    i += len(parts)
                    matched = True
                    break
            if not matched:
                i += 1
    return intervals


def shrink_silence_for_padding(start: float, end: float) -> tuple[float, float] | None:
    """Keep padding near speech; return inner region to remove, or None."""
    inner_start = start + SPEECH_PADDING
    inner_end = end - SPEECH_PADDING
    if inner_end - inner_start < 0.05:
        return None
    return inner_start, inner_end


def speech_keep_segments(transcript: dict, duration: float) -> list[tuple[float, float]]:
    """Keep speech from word timestamps, with padding; drop long pauses between word groups."""
    words: list[dict] = []
    for seg in transcript.get("segments") or []:
        words.extend(seg.get("words") or [])
    if not words:
        return []

    words.sort(key=lambda w: float(w["start"]))
    groups: list[list[dict]] = [[words[0]]]
    for w in words[1:]:
        gap = float(w["start"]) - float(groups[-1][-1]["end"])
        if gap >= SILENCE_REMOVE_MIN:
            groups.append([w])
        else:
            groups[-1].append(w)

    keeps: list[tuple[float, float]] = []
    for group in groups:
        start = max(0.0, float(group[0]["start"]) - SPEECH_PADDING)
        end = min(duration, float(group[-1]["end"]) + SPEECH_PADDING)
        if end - start > 0.05:
            keeps.append((start, end))
    return merge_close_keeps(keeps)


def invert_removals(
    duration: float,
    removals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Complement of removal intervals → keep segments within [0, duration]."""
    if not removals:
        return [(0.0, duration)]

    removals = sorted(removals)
    merged: list[tuple[float, float]] = []
    for start, end in removals:
        start = max(0.0, start)
        end = min(duration, end)
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in merged:
        if start > cursor + 0.01:
            keeps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.01:
        keeps.append((cursor, duration))
    return keeps


def subtract_intervals(
    keeps: list[tuple[float, float]],
    cuts: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Remove cut ranges from keep ranges (used for filler words)."""
    result: list[tuple[float, float]] = []
    for ks, ke in keeps:
        spans = [(ks, ke)]
        for cs, ce in sorted(cuts):
            next_spans: list[tuple[float, float]] = []
            for s, e in spans:
                if ce <= s or cs >= e:
                    next_spans.append((s, e))
                else:
                    if s < cs:
                        next_spans.append((s, cs))
                    if ce < e:
                        next_spans.append((ce, e))
            spans = next_spans
        result.extend(spans)
    return merge_close_keeps([s for s in result if s[1] - s[0] > 0.05])


def merge_close_keeps(segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not segments:
        return segments
    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= MERGE_GAP:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def build_plan(
    video_path: Path,
    remove_fillers: bool,
) -> tuple[list[dict], float, float]:
    duration = video_duration_seconds(video_path)
    t_path = transcript_path(video_path)
    s_path = silences_path(video_path)

    silences_doc = load_json(s_path)
    if not silences_doc:
        print(f"Error: missing {s_path}; run silences.py first", file=sys.stderr)
        sys.exit(1)

    silences = silences_doc.get("silences") or []
    removals: list[tuple[float, float]] = []

    for s in silences:
        start, end = float(s["start"]), float(s["end"])
        if end - start < SILENCE_REMOVE_MIN:
            continue
        inner = shrink_silence_for_padding(start, end)
        if inner:
            removals.append(inner)

    transcript = load_json(t_path)
    keeps: list[tuple[float, float]]

    if transcript and any(
        seg.get("words") for seg in (transcript.get("segments") or [])
    ):
        keeps = speech_keep_segments(transcript, duration)
        if remove_fillers:
            fillers = collect_filler_intervals(transcript)
            if fillers:
                keeps = subtract_intervals(keeps, fillers)
    elif transcript:
        print(f"Warning: no word timestamps in {t_path}", file=sys.stderr)
        keeps = merge_close_keeps(invert_removals(duration, removals))
    else:
        print(
            f"Warning: missing {t_path}; using silences only",
            file=sys.stderr,
        )
        for s in silences:
            start, end = float(s["start"]), float(s["end"])
            if end - start >= SILENCE_REMOVE_MIN:
                inner = shrink_silence_for_padding(start, end)
                if inner:
                    removals.append(inner)
        keeps = merge_close_keeps(invert_removals(duration, removals))

    return _finish_plan(video_path, keeps, duration)


def _finish_plan(
    video_path: Path,
    keeps: list[tuple[float, float]],
    duration: float,
) -> tuple[list[dict], float, float]:
    kept_seconds = sum(e - s for s, e in keeps)
    removed_seconds = max(duration - kept_seconds, 0.0)

    source = str(video_path)
    timeline = [
        {
            "source": source,
            "start": round(s, 3),
            "end": round(e, 3),
        }
        for s, e in keeps
    ]
    return timeline, kept_seconds, removed_seconds


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a tightened edit plan JSON")
    parser.add_argument("video_path")
    parser.add_argument(
        "--remove-fillers",
        action="store_true",
        help="Also cut common filler words using transcript word timestamps",
    )
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    timeline, kept_seconds, removed_seconds = build_plan(
        video_path, args.remove_fillers
    )

    plans_dir = Path.cwd() / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    out_path = plans_dir / f"{video_path.stem}_tight.json"
    payload = {
        "name": f"{video_path.stem}_tight",
        "segments": timeline,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"Wrote plan: {out_path}")
    print(f"Keep segments: {len(timeline)}  ({kept_seconds:.2f}s kept)")
    print(f"Removed (silence/fillers): {removed_seconds:.2f}s")


if __name__ == "__main__":
    main()
