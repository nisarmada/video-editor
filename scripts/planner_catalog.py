"""
Two-level media catalog for the planner.

Compact entries stay under a token budget. Detail (words, shots, frames)
is built only when something asks for one file and a time range.
Ranking uses a local hashed embedding cached under index/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from text_embeddings import (
    ensure_file_embedding,
    hash_embed,
    relevance_for_entry,
    score_brief_against_payload,
    sentences_from_catalog_entry,
)
from planner_limits import estimate_tokens
DIGEST_SENTENCES = 3
DIGEST_CHARS = 320

# Static instructions cached across runs. The brief is not part of this.
RUBRIC = """Rubric (static):
- Draft mode sends a compact catalog only. No images are attached.
- Use only files listed in the catalog. Do not invent filenames or times past a file's duration.
- transcript_digest is a short excerpt, not every word. Keep trims inside the file duration.
- Return one JSON object. No markdown fences and no explanation.
"""


def _sentences(text: str, limit: int = DIGEST_SENTENCES, max_chars: int = DIGEST_CHARS) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", clean)
    chosen: list[str] = []
    for part in parts:
        bit = part.strip()
        if not bit:
            continue
        chosen.append(bit)
        if len(chosen) >= limit:
            break
    out = " ".join(chosen)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out


def _summary_line(entry: dict) -> str:
    captions = entry.get("ai_frame_captions") or []
    if isinstance(captions, list):
        for frame in captions:
            if isinstance(frame, dict):
                desc = str(frame.get("description") or frame.get("caption") or "").strip()
                if desc:
                    return _sentences(desc, limit=1, max_chars=140)
    segments = entry.get("transcript_segments") or []
    if isinstance(segments, list):
        for seg in segments:
            if isinstance(seg, dict):
                text = str(seg.get("text") or "").strip()
                if text and text.lower() != "no speech detected":
                    return _sentences(text, limit=1, max_chars=140)
    kind = entry.get("kind") or "file"
    dur = entry.get("duration_seconds") or 0
    return f"{kind}, {dur}s"


def _digest(entry: dict) -> str:
    chunks: list[str] = []
    segments = entry.get("transcript_segments") or []
    if isinstance(segments, list):
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text") or "").strip()
            if not text or text.lower() in {"no speech detected", "not analyzed"}:
                continue
            chunks.append(text)
    return _sentences(" ".join(chunks))


def _analysis_status(entry: dict) -> dict[str, Any]:
    raw = entry.get("analysis") or {}
    if not isinstance(raw, dict):
        return {}
    status: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            status[key] = value.get("status")
        else:
            status[key] = value
    return status


def to_compact(entry: dict) -> dict[str, Any]:
    """One cheap row: identity, a one-line summary, measurements, a short digest."""
    shots = entry.get("shots") or []
    words = entry.get("transcript_words") or []
    perc = entry.get("perception_summary") if isinstance(entry.get("perception_summary"), dict) else {}
    audio = (
        entry.get("audio_perception_summary")
        if isinstance(entry.get("audio_perception_summary"), dict)
        else {}
    )
    return {
        "id": entry.get("id"),
        "kind": entry.get("kind"),
        "duration_seconds": entry.get("duration_seconds"),
        "summary": _summary_line(entry),
        "measurements": {
            "silence_ratio": entry.get("silence_ratio_estimate"),
            "shot_count": len(shots) if isinstance(shots, list) else 0,
            "word_count": len(words) if isinstance(words, list) else 0,
            "has_audio": entry.get("has_audio"),
            "width": entry.get("width"),
            "height": entry.get("height"),
            "mean_motion_level": perc.get("mean_motion_level"),
            "mean_shake_score": perc.get("mean_shake_score"),
            "mean_brightness": perc.get("mean_brightness"),
            "mean_contrast": perc.get("mean_contrast"),
            "perception_status": perc.get("status"),
            "loudness_lufs": audio.get("loudness_lufs"),
            "speech_rate_wpm": audio.get("speech_rate_wpm"),
            "pause_ratio": audio.get("pause_ratio"),
            "longest_pause_s": audio.get("longest_pause_s"),
            "filler_count": audio.get("filler_count"),
            "audio_perception_status": audio.get("status"),
            "take_count": (
                entry.get("takes_summary", {}).get("take_count")
                if isinstance(entry.get("takes_summary"), dict)
                else None
            ),
            "phrase_group_count": (
                entry.get("takes_summary", {}).get("phrase_group_count")
                if isinstance(entry.get("takes_summary"), dict)
                else None
            ),
            "takes_status": (
                entry.get("takes_summary", {}).get("status")
                if isinstance(entry.get("takes_summary"), dict)
                else None
            ),
        },
        "analysis": _analysis_status(entry),
        "transcript_digest": _digest(entry),
    }


def is_analyzed(entry: dict) -> bool:
    status = (entry.get("analysis") or {}).get("merged_index")
    return status == "complete"


def detail_slice(
    entry: dict,
    *,
    start: float | None = None,
    end: float | None = None,
) -> dict[str, Any]:
    """
    Full words, shots, and keyframe captions for one file.
    Optional start/end keep only words that overlap that range.
    """
    words_out: list[dict] = []
    for word in entry.get("transcript_words") or []:
        if not isinstance(word, dict):
            continue
        try:
            w0 = float(word["start"])
            w1 = float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start is not None and w1 < start:
            continue
        if end is not None and w0 > end:
            continue
        words_out.append(word)
    return {
        "id": entry.get("id"),
        "transcript_words": words_out,
        "shots": entry.get("shots") or [],
        "keyframes": entry.get("keyframes") or [],
        "ai_frame_captions": entry.get("ai_frame_captions") or [],
        "perception_shots": entry.get("perception_shots") or [],
        "perception_summary": entry.get("perception_summary"),
        "audio_perception_summary": entry.get("audio_perception_summary"),
        "audio_perception_windows": entry.get("audio_perception_windows") or [],
        "takes_summary": entry.get("takes_summary"),
        "takes": entry.get("takes") or [],
        "phrase_groups": entry.get("phrase_groups") or [],
    }


def embedding_for_id(file_id: str, text: str) -> list[float]:
    """Backward-compatible mean vector from a single text blob."""
    payload = ensure_file_embedding(
        file_id,
        sentences=[s for s in re.split(r"\s{2,}", text) if s.strip()] or [text],
    )
    vec = payload.get("vector")
    if isinstance(vec, list):
        return [float(v) for v in vec]
    return hash_embed(text)


def catalog_json(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def _shrink_entry(entry: dict, budget: int) -> dict:
    """Shorten one row until a single-item catalog fits the budget."""
    current = dict(entry)
    while estimate_tokens(catalog_json([current])) > budget and current.get("transcript_digest"):
        digest = str(current["transcript_digest"])
        current["transcript_digest"] = digest[: max(0, len(digest) - 40)]
    if estimate_tokens(catalog_json([current])) > budget:
        current["transcript_digest"] = ""
        current["summary"] = str(current.get("summary") or "")[:80]
    return current


def select_compact(
    full_entries: list[dict],
    brief: str,
    budget_tokens: int,
) -> tuple[list[dict], int, list[str]]:
    """
    Return (compact rows to send, omitted analyzed count, unanalyzed ids).
    Unanalyzed files are never included.
    """
    unanalyzed = [
        str(entry.get("id"))
        for entry in full_entries
        if entry.get("id") and not is_analyzed(entry)
    ]
    compact = [to_compact(entry) for entry in full_entries if is_analyzed(entry)]
    if estimate_tokens(catalog_json(compact)) <= budget_tokens:
        return compact, 0, unanalyzed

    scored: list[tuple[float, dict]] = []
    entry_by_id = {
        str(e.get("id")): e
        for e in full_entries
        if e.get("id") and is_analyzed(e)
    }
    for row in compact:
        entry = entry_by_id.get(str(row.get("id") or ""))
        if entry:
            score = relevance_for_entry(brief, entry)
        else:
            score = score_brief_against_payload(
                brief,
                ensure_file_embedding(
                    str(row.get("id") or "file"),
                    sentences=sentences_from_catalog_entry(
                        {
                            "transcript_segments": [{"text": row.get("transcript_digest")}],
                        }
                    ),
                ),
            )
        scored.append((score, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    chosen: list[dict] = []
    for _score, row in scored:
        trial = chosen + [row]
        if estimate_tokens(catalog_json(trial)) <= budget_tokens:
            chosen.append(row)
            continue
        if not chosen:
            chosen.append(_shrink_entry(row, budget_tokens))
        break
    omitted = max(0, len(compact) - len(chosen))
    return chosen, omitted, unanalyzed


def catalog_block(rows: list[dict], *, omitted: int, unanalyzed: list[str]) -> str:
    lines = [
        "Media catalog (JSON):",
        catalog_json(rows),
        f"Analyzed files included: {len(rows)}.",
    ]
    if omitted:
        lines.append(
            f"Omitted {omitted} analyzed files to stay inside the catalog token budget."
        )
    if unanalyzed:
        lines.append(
            "Not sent because analysis is missing: " + ", ".join(unanalyzed) + "."
        )
    return "\n".join(lines)


def files_mentioned(plan: dict, errors: list[str]) -> set[str]:
    blob = json.dumps(plan, ensure_ascii=False) + "\n" + "\n".join(errors)
    names = set(re.findall(r"footage/([^\s\"'\\]+)", blob))
    return {Path(name).name for name in names}


def invalid_plan_parts(plan: dict, errors: list[str]) -> dict:
    """Tracks and clips the error text or sources actually mention."""
    names = files_mentioned(plan, errors)
    error_blob = "\n".join(errors)
    tracks_out: list[dict] = []
    for track in plan.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        clips_out = []
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            source = str(clip.get("source") or "")
            base = Path(source).name
            clip_id = str(clip.get("id") or "")
            if base in names or (clip_id and clip_id in error_blob) or base in error_blob:
                clips_out.append(clip)
        if clips_out:
            copy = dict(track)
            copy["clips"] = clips_out
            tracks_out.append(copy)
    if not tracks_out:
        tracks_out = list(plan.get("tracks") or [])
    return {"schema_version": plan.get("schema_version", 2), "tracks": tracks_out}


def build_repair_prompt(
    plan: dict,
    errors: list[str],
    compact_rows: list[dict],
) -> str:
    """
    Repair context: the broken clips, the error list, and only the catalog
    rows for files those clips use. Other files are left out.
    """
    names = files_mentioned(plan, errors)
    involved = [row for row in compact_rows if str(row.get("id")) in names]
    parts = invalid_plan_parts(plan, errors)
    return (
        "Fix the timeline JSON. Reply with one JSON object only.\n\n"
        "Errors:\n"
        + "\n".join(f"- {err}" for err in errors)
        + "\n\nInvalid plan parts (JSON):\n"
        + catalog_json(parts)
        + "\n\nCatalog entries for the files involved:\n"
        + catalog_json(involved)
    )


def cached_system_blocks(base_prompt: str, extra: str | None = None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": base_prompt,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": RUBRIC,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    if extra:
        blocks.append({"type": "text", "text": extra})
    return blocks


def user_content_blocks(catalog_text: str, brief_text: str) -> list[dict[str, Any]]:
    """Catalog is the cached prefix. The brief changes every run and is not cached."""
    return [
        {
            "type": "text",
            "text": catalog_text,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": brief_text},
    ]


def content_as_text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            parts.append(str(block.get("text") or ""))
        else:
            parts.append(str(block))
    return "\n".join(parts)
