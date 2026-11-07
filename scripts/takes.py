#!/usr/bin/env python3
"""
Group speech into takes: near-duplicate phrase clusters, restarts, abandoned
lines, and per-attempt delivery measurements. No paid API.

Usage: python scripts/takes.py <media_path> [--force]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from audio_perception import collect_words  # noqa: E402
from index_cache import (  # noqa: E402
    audio_perception_path,
    cache_hit,
    load_json,
    save_json,
    takes_path,
    transcript_path,
)
from media import clip_metadata  # noqa: E402
from transcribe import has_audio_track, video_duration_seconds  # noqa: E402

# Gap between words that starts a new utterance (new line attempt).
UTTERANCE_GAP_S = 0.85
# Fuzzy match threshold for grouping attempts at the same phrase.
PHRASE_MATCH_MIN = 0.62


def normalize_phrase(text: str) -> str:
    tokens = re.findall(r"[a-z0-9']+", (text or "").lower())
    return " ".join(tokens)


def phrase_similarity(a: str, b: str) -> float:
    ra = normalize_phrase(a)
    rb = normalize_phrase(b)
    if not ra or not rb:
        return 0.0
    seq = SequenceMatcher(None, ra, rb).ratio()
    ta, tb = set(ra.split()), set(rb.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(seq, jaccard)


def ends_complete_sentence(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return t[-1] in ".!?"


def utterances_from_words(words: list[dict]) -> list[dict]:
    if not words:
        return []
    utterances: list[dict] = []
    bucket: list[dict] = [words[0]]
    for w in words[1:]:
        gap = float(w["start"]) - float(bucket[-1]["end"])
        if gap >= UTTERANCE_GAP_S:
            utterances.append(_pack_utterance(bucket))
            bucket = [w]
        else:
            bucket.append(w)
    utterances.append(_pack_utterance(bucket))
    return utterances


def _pack_utterance(word_rows: list[dict]) -> dict:
    text = " ".join(str(w.get("word") or "").strip() for w in word_rows).strip()
    return {
        "start": float(word_rows[0]["start"]),
        "end": float(word_rows[-1]["end"]),
        "text": text,
        "words": list(word_rows),
    }


def cluster_utterances(utterances: list[dict]) -> list[dict]:
    groups: list[dict] = []
    for utt in utterances:
        best_i: int | None = None
        best_score = 0.0
        for i, g in enumerate(groups):
            score = phrase_similarity(utt["text"], str(g.get("phrase") or ""))
            if score > best_score:
                best_score = score
                best_i = i
        if best_i is not None and best_score >= PHRASE_MATCH_MIN:
            g = groups[best_i]
            g["attempts"].append(utt)
            if len(normalize_phrase(utt["text"])) > len(
                normalize_phrase(str(g.get("phrase") or ""))
            ):
                g["phrase"] = utt["text"]
                g["phrase_normalized"] = normalize_phrase(utt["text"])
        else:
            groups.append(
                {
                    "phrase": utt["text"],
                    "phrase_normalized": normalize_phrase(utt["text"]),
                    "attempts": [utt],
                }
            )
    for i, g in enumerate(groups):
        g["group_index"] = i
        g["attempt_count"] = len(g.get("attempts") or [])
    return groups


def _windows_in_range(
    windows: list[dict], t0: float, t1: float
) -> list[dict]:
    out: list[dict] = []
    for w in windows:
        if not isinstance(w, dict):
            continue
        try:
            ws = float(w["start"])
            we = float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if we <= t0 or ws >= t1:
            continue
        out.append(w)
    return out


def _loudness_stats(windows: list[dict], t0: float, t1: float) -> tuple[float | None, float | None]:
    rows = _windows_in_range(windows, t0, t1)
    vals: list[float] = []
    for w in rows:
        rms = w.get("rms_db")
        if isinstance(rms, (int, float)):
            vals.append(float(rms))
    if not vals:
        return None, None
    mean = sum(vals) / len(vals)
    if len(vals) < 2:
        return round(mean, 2), 0.0
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return round(mean, 2), round(var, 3)


def _internal_pauses(words: list[dict]) -> tuple[float | None, float | None]:
    if len(words) < 2:
        return 0.0, 0.0
    gaps: list[float] = []
    for i in range(1, len(words)):
        gap = float(words[i]["start"]) - float(words[i - 1]["end"])
        if gap > 0.05:
            gaps.append(gap)
    span = max(0.1, float(words[-1]["end"]) - float(words[0]["start"]))
    pause_time = sum(gaps)
    longest = max(gaps) if gaps else 0.0
    ratio = round(min(1.0, pause_time / span), 4)
    return ratio, round(longest, 3)


def _speech_rate_wpm(words: list[dict], t0: float, t1: float) -> float | None:
    if not words:
        return None
    span = max(0.1, t1 - t0)
    return round(len(words) / (span / 60.0), 1)


def build_takes(media_path: Path, *, force: bool = False) -> dict:
    media_path = media_path.resolve()
    out_path = takes_path(media_path)
    if cache_hit(out_path, force) and not force:
        data = load_json(out_path)
        if isinstance(data, dict):
            return data

    duration_meta, has_audio, _ = clip_metadata(media_path)
    duration = float(video_duration_seconds(media_path) or duration_meta or 0.0)

    if not has_audio_track(media_path):
        payload = {
            "clip": media_path.name,
            "has_audio": False,
            "has_speech": False,
            "duration_seconds": round(duration, 6),
            "version": 1,
            "phrase_groups": [],
            "takes": [],
        }
        save_json(out_path, payload)
        return payload

    t0 = time.perf_counter()
    transcript = load_json(transcript_path(media_path)) or {}
    words = collect_words(transcript if isinstance(transcript, dict) else {})
    audio_doc = load_json(audio_perception_path(media_path)) or {}
    windows: list[dict] = []
    if isinstance(audio_doc, dict):
        raw = audio_doc.get("windows")
        if isinstance(raw, list):
            windows = raw

    if not words:
        payload = {
            "clip": media_path.name,
            "has_audio": True,
            "has_speech": False,
            "duration_seconds": round(duration, 6),
            "version": 1,
            "phrase_groups": [],
            "takes": [],
            "timing_ms": {"total": int((time.perf_counter() - t0) * 1000)},
        }
        save_json(out_path, payload)
        return payload

    utterances = utterances_from_words(words)
    groups = cluster_utterances(utterances)
    takes: list[dict] = []
    take_index = 0
    for group in groups:
        attempts = group.get("attempts") or []
        for attempt_i, utt in enumerate(attempts):
            if not isinstance(utt, dict):
                continue
            start = float(utt["start"])
            end = float(utt["end"])
            utt_words = utt.get("words") or []
            complete = ends_complete_sentence(str(utt.get("text") or ""))
            is_restart = attempt_i > 0
            abandoned = (not complete) and (attempt_i < len(attempts) - 1)
            pause_ratio, longest_pause = _internal_pauses(
                utt_words if isinstance(utt_words, list) else []
            )
            loud_mean, loud_var = _loudness_stats(windows, start, end)
            takes.append(
                {
                    "take_index": take_index,
                    "phrase_group": int(group.get("group_index", 0)),
                    "attempt_in_group": attempt_i,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": utt.get("text") or "",
                    "is_restart": is_restart,
                    "abandoned_sentence": abandoned,
                    "ends_complete_sentence": complete,
                    "speech_rate_wpm": _speech_rate_wpm(
                        utt_words if isinstance(utt_words, list) else [],
                        start,
                        end,
                    ),
                    "loudness_mean_db": loud_mean,
                    "loudness_variance_db2": loud_var,
                    "pause_ratio": pause_ratio,
                    "longest_internal_pause_s": longest_pause,
                    "word_count": len(utt_words) if isinstance(utt_words, list) else 0,
                }
            )
            take_index += 1

    phrase_groups = [
        {
            "group_index": g.get("group_index"),
            "phrase_normalized": g.get("phrase_normalized"),
            "attempt_count": g.get("attempt_count"),
        }
        for g in groups
    ]

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    payload = {
        "clip": media_path.name,
        "has_audio": True,
        "has_speech": True,
        "duration_seconds": round(duration, 6),
        "version": 1,
        "phrase_groups": phrase_groups,
        "takes": takes,
        "timing_ms": {"total": elapsed_ms},
    }
    save_json(out_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect speech takes from transcript")
    parser.add_argument("media_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    path = Path(args.media_path)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    out_path = takes_path(path)
    if cache_hit(out_path, args.force) and not args.force:
        print(f"Using cached takes: {out_path}")
        return

    try:
        payload = build_takes(path, force=args.force)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Saved: {out_path}  takes={len(payload.get('takes') or [])}  "
        f"groups={len(payload.get('phrase_groups') or [])}"
    )


if __name__ == "__main__":
    main()
