#!/usr/bin/env python3
"""
Multi-granularity speech units from word-level transcripts (sentences, phrases, words).
Measurements only — no editorial verdicts. Cached under index/.

Usage: python scripts/speech_units.py <media_path> [--force]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from audio_perception import collect_words  # noqa: E402
from index_cache import (  # noqa: E402
    cache_hit,
    load_json,
    save_json_atomic,
    speech_units_path,
    transcript_path,
    waveform_path,
)

PHRASE_GAP_S = 0.42
CLAUSE_SPLIT_RE = re.compile(r"[,;:]\s*", re.UNICODE)

CONNECTIVE_START = frozenset(
    {
        "and",
        "but",
        "or",
        "so",
        "because",
        "when",
        "while",
        "if",
        "though",
        "although",
        "however",
        "then",
        "well",
        "like",
        "yet",
        "nor",
        "plus",
        "minus",
        "whereas",
        "on",
        "off",
    }
)

FUNCTION_OR_CONNECTIVE_END = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "but",
        "or",
        "so",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "that",
        "which",
        "who",
        "whom",
        "as",
        "by",
        "from",
        "into",
        "through",
        "after",
        "before",
        "other",
        "than",
        "into",
        "onto",
        "upon",
        "over",
        "under",
        "about",
        "between",
        "during",
        "without",
        "within",
        "along",
        "around",
    }
)


def _token(word: str) -> str:
    return re.sub(r"[^\w']", "", (word or "").lower())


def _ends_terminal(text: str) -> bool:
    t = (text or "").rstrip()
    return bool(t) and t[-1] in ".!?"


def _starts_connective(text: str) -> bool:
    parts = (text or "").strip().split()
    if not parts:
        return False
    return _token(parts[0]) in CONNECTIVE_START


def _ends_connective_or_function(text: str) -> bool:
    parts = (text or "").strip().split()
    if not parts:
        return False
    return _token(parts[-1]) in FUNCTION_OR_CONNECTIVE_END


def _rms_at(peaks: list, sr: float, t: float) -> float:
    i = int(t * sr)
    if i < 0 or i >= len(peaks):
        return 0.0
    bucket = peaks[i]
    if not isinstance(bucket, (list, tuple)) or len(bucket) < 2:
        return 0.0
    return max(abs(float(bucket[0])), abs(float(bucket[1])))


def _avg_rms(peaks: list, sr: float, t0: float, t1: float) -> float:
    if t1 <= t0:
        return 0.0
    step = 1.0 / sr
    t = t0
    vals: list[float] = []
    while t <= t1 + 1e-9:
        vals.append(_rms_at(peaks, sr, t))
        t += step
    return sum(vals) / len(vals) if vals else 0.0


def _energy_falloff(
    unit_end: float,
    peaks: list | None,
    sr: float,
    *,
    window_s: float = 0.2,
) -> float | None:
    if not peaks:
        return None
    tail0 = max(0.0, unit_end - window_s)
    prev0 = max(0.0, unit_end - 2 * window_s)
    tail = _avg_rms(peaks, sr, tail0, unit_end)
    prev = _avg_rms(peaks, sr, prev0, tail0)
    if prev <= 1e-9:
        return 0.0 if tail <= 1e-9 else 1.0
    drop = max(0.0, (prev - tail) / prev)
    return round(min(1.0, drop), 4)


def _trailing_pause(unit_end: float, next_start: float | None) -> float | None:
    if next_start is None:
        return None
    gap = float(next_start) - float(unit_end)
    return round(max(0.0, gap), 4)


def _pack_unit(
    words: list[dict],
    *,
    granularity: str,
    unit_id: str,
    next_word_start: float | None,
    peaks: list | None,
    sr: float,
) -> dict:
    text = " ".join(str(w.get("word") or "").strip() for w in words).strip()
    start = float(words[0]["start"])
    end = float(words[-1]["end"])
    return {
        "id": unit_id,
        "granularity": granularity,
        "start": round(start, 4),
        "end": round(end, 4),
        "text": text,
        "word_count": len(words),
        "ends_terminal_punctuation": _ends_terminal(text),
        "trailing_pause_s": _trailing_pause(end, next_word_start),
        "energy_falloff_last_200ms": _energy_falloff(end, peaks, sr),
        "starts_with_connective": _starts_connective(text),
        "ends_with_connective_or_function": _ends_connective_or_function(text),
    }


def sentences_from_words(words: list[dict]) -> list[list[dict]]:
    if not words:
        return []
    out: list[list[dict]] = []
    bucket: list[dict] = []
    for w in words:
        bucket.append(w)
        raw = str(w.get("word") or "")
        if raw.rstrip().endswith((".", "!", "?")):
            out.append(bucket)
            bucket = []
    if bucket:
        out.append(bucket)
    return out


def phrases_from_sentence(sent_words: list[dict]) -> list[list[dict]]:
    """Split on long gaps, commas, or conjunction tokens."""
    if not sent_words:
        return []
    phrases: list[list[dict]] = []
    bucket: list[dict] = [sent_words[0]]
    for w in sent_words[1:]:
        gap = float(w["start"]) - float(bucket[-1]["end"])
        tok = _token(str(w.get("word") or ""))
        prev_tok = _token(str(bucket[-1].get("word") or ""))
        split = gap >= PHRASE_GAP_S
        split = split or tok in CONNECTIVE_START
        split = split or prev_tok.endswith(",")
        if split:
            phrases.append(bucket)
            bucket = [w]
        else:
            bucket.append(w)
    if bucket:
        phrases.append(bucket)
    # secondary: split comma runs inside long phrases
    refined: list[list[dict]] = []
    for phrase in phrases:
        text = " ".join(str(x.get("word") or "") for x in phrase)
        if "," not in text or len(phrase) <= 4:
            refined.append(phrase)
            continue
        # keep word groups between comma markers
        sub: list[dict] = []
        for w in phrase:
            sub.append(w)
            if str(w.get("word") or "").rstrip().endswith(","):
                refined.append(sub)
                sub = []
        if sub:
            refined.append(sub)
    return refined or [sent_words]


def build_speech_units(
    media_path: Path,
    *,
    transcript_doc: dict | None = None,
    waveform_doc: dict | None = None,
) -> dict:
    words = collect_words(transcript_doc or load_json(transcript_path(media_path)) or {})
    peaks: list = []
    sr = 100.0
    if isinstance(waveform_doc, dict):
        peaks = waveform_doc.get("peaks") or []
        sr = float(waveform_doc.get("sample_rate_hz_of_peaks") or 100.0)
    else:
        wf = load_json(waveform_path(media_path))
        if isinstance(wf, dict):
            peaks = wf.get("peaks") or []
            sr = float(wf.get("sample_rate_hz_of_peaks") or 100.0)

    units: list[dict] = []
    word_units: list[dict] = []
    for i, w in enumerate(words):
        nxt = float(words[i + 1]["start"]) if i + 1 < len(words) else None
        word_units.append(
            _pack_unit(
                [w],
                granularity="word",
                unit_id=f"w{i}",
                next_word_start=nxt,
                peaks=peaks,
                sr=sr,
            )
        )

    sent_groups = sentences_from_words(words)
    sentence_units: list[dict] = []
    for si, sent in enumerate(sent_groups):
        nxt = None
        if si + 1 < len(sent_groups):
            nxt = float(sent_groups[si + 1][0]["start"])
        elif words and float(sent[-1]["end"]) < float(words[-1]["end"]):
            # trailing material in same stream
            for w in words:
                if float(w["start"]) > float(sent[-1]["end"]) + 0.01:
                    nxt = float(w["start"])
                    break
        sentence_units.append(
            _pack_unit(
                sent,
                granularity="sentence",
                unit_id=f"s{si}",
                next_word_start=nxt,
                peaks=peaks,
                sr=sr,
            )
        )

    phrase_units: list[dict] = []
    pi = 0
    for sent in sent_groups:
        for chunk in phrases_from_sentence(sent):
            nxt = None
            for w in words:
                if float(w["start"]) > float(chunk[-1]["end"]) + 0.01:
                    nxt = float(w["start"])
                    break
            phrase_units.append(
                _pack_unit(
                    chunk,
                    granularity="phrase",
                    unit_id=f"p{pi}",
                    next_word_start=nxt,
                    peaks=peaks,
                    sr=sr,
                )
            )
            pi += 1

    units.extend(sentence_units)
    units.extend(phrase_units)
    units.extend(word_units)

    return {
        "clip": media_path.name,
        "unit_count": len(units),
        "sentences": sentence_units,
        "phrases": phrase_units,
        "words": word_units,
        "units": units,
    }


def compact_speech_digest(doc: dict, *, limit: int = 10) -> list[dict]:
    phrases = doc.get("phrases") if isinstance(doc.get("phrases"), list) else []
    out: list[dict] = []
    for row in phrases[:limit]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "")
        if len(text) > 96:
            text = text[:93].rstrip() + "…"
        out.append(
            {
                "id": row.get("id"),
                "start": row.get("start"),
                "end": row.get("end"),
                "text": text,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build speech unit index")
    parser.add_argument("media_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    media = Path(args.media_path).resolve()
    if not media.is_file():
        print(f"Error: not found: {media}", file=sys.stderr)
        sys.exit(1)
    out_path = speech_units_path(media)
    if cache_hit(out_path, args.force):
        print(f"Using cached speech units: {out_path}")
        return
    tr = load_json(transcript_path(media))
    if not tr:
        print("Error: run transcribe.py first", file=sys.stderr)
        sys.exit(1)
    payload = build_speech_units(media, transcript_doc=tr)
    save_json_atomic(out_path, payload)
    print(f"Wrote {out_path} ({payload['unit_count']} units)")


if __name__ == "__main__":
    main()
