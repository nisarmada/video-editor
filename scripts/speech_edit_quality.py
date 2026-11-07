"""Speech edit warnings (non-blocking) and read-back assembly for the judge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from index_cache import load_json, speech_units_path, transcript_path
from speech_units import FUNCTION_OR_CONNECTIVE_END, _token, build_speech_units


def _resolve_source(source: str, root: Path) -> Path | None:
    rel = source.replace("\\", "/")
    if rel.startswith("footage/"):
        p = root / rel
        return p if p.is_file() else None
    p = root / "footage" / Path(rel).name
    return p if p.is_file() else None


def flatten_words(tr: dict | None) -> list[dict]:
    if not tr:
        return []
    out: list[dict] = []
    for seg in tr.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        for w in seg.get("words") or []:
            if isinstance(w, dict) and "start" in w and "end" in w:
                out.append(w)
    out.sort(key=lambda w: float(w["start"]))
    return out


def audible_speech_clips(timeline: dict) -> list[dict]:
    """Audio track clips + embedded-audio video clips, timeline order."""
    rows: list[dict] = []
    for track in timeline.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        ttype = track.get("type")
        if ttype == "audio":
            for clip in track.get("clips") or []:
                if isinstance(clip, dict):
                    rows.append(
                        {
                            **clip,
                            "_track_id": track.get("id"),
                            "_track_type": "audio",
                        }
                    )
        elif ttype == "video":
            for clip in track.get("clips") or []:
                if not isinstance(clip, dict):
                    continue
                if clip.get("audio_source") == "detached":
                    continue
                rows.append(
                    {
                        **clip,
                        "_track_id": track.get("id"),
                        "_track_type": "video",
                    }
                )
    rows.sort(key=lambda c: float(c.get("timeline_start") or 0))
    return rows


def _clip_words(root: Path, source: str, si: float, so: float) -> list[dict]:
    path = _resolve_source(source, root)
    if not path:
        return []
    tr = load_json(transcript_path(path))
    words = flatten_words(tr if isinstance(tr, dict) else None)
    return [w for w in words if float(w["end"]) > si and float(w["start"]) < so]


def _boundary_word(words: list[dict], t: float, *, edge: str) -> dict | None:
    if not words:
        return None
    if edge == "start":
        for w in words:
            if abs(float(w["start"]) - t) < 0.08:
                return w
        for w in words:
            if float(w["start"]) >= t - 0.03:
                return w
    else:
        for w in reversed(words):
            if abs(float(w["end"]) - t) < 0.08:
                return w
        for w in reversed(words):
            if float(w["end"]) <= t + 0.03:
                return w
    return None


def _parse_cut_intent(clip: dict) -> dict | None:
    raw = clip.get("cut_intent")
    if not isinstance(raw, dict):
        return None
    return raw


def assemble_readback(timeline: dict, *, root: Path) -> list[dict]:
    """Ordered speech blocks with text and declared intent."""
    blocks: list[dict] = []
    for clip in audible_speech_clips(timeline):
        try:
            si = float(clip["source_in"])
            so = float(clip["source_out"])
        except (KeyError, TypeError, ValueError):
            continue
        words = _clip_words(root, str(clip.get("source") or ""), si, so)
        text = " ".join(str(w.get("word") or "") for w in words).strip()
        intent = _parse_cut_intent(clip) or {
            "start": "complete",
            "end": "complete",
        }
        blocks.append(
            {
                "clip_id": clip.get("id"),
                "source": clip.get("source"),
                "timeline_start": clip.get("timeline_start"),
                "source_in": si,
                "source_out": so,
                "text": text,
                "cut_intent": intent,
            }
        )
    return blocks


def mechanical_speech_warnings(
    timeline: dict,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    root = root or Path.cwd()
    warnings: list[dict[str, Any]] = []
    clips = audible_speech_clips(timeline)
    if not clips:
        return warnings

    seen_phrases: dict[str, str] = {}
    last_video_end = 0.0
    for track in timeline.get("tracks") or []:
        if track.get("type") == "video":
            for c in track.get("clips") or []:
                try:
                    tl = float(c.get("timeline_start", 0))
                    dur = float(c["source_out"]) - float(c["source_in"])
                    last_video_end = max(last_video_end, tl + dur)
                except (KeyError, TypeError, ValueError):
                    pass

    speech_end = 0.0
    for i, clip in enumerate(clips):
        cid = str(clip.get("id") or f"clip{i}")
        try:
            si = float(clip["source_in"])
            so = float(clip["source_out"])
            tl = float(clip.get("timeline_start", 0))
        except (KeyError, TypeError, ValueError):
            continue
        dur = max(0.0, so - si)
        speech_end = max(speech_end, tl + dur)
        words = _clip_words(root, str(clip.get("source") or ""), si, so)
        if not words:
            continue
        text = " ".join(str(w.get("word") or "") for w in words)
        norm = " ".join(_token(x) for x in text.split())
        if norm and norm in seen_phrases:
            warnings.append(
                {
                    "code": "duplicate_phrase",
                    "severity": "info",
                    "clip_id": cid,
                    "message": f"Same speech text used again (first in {seen_phrases[norm]}).",
                }
            )
        elif norm:
            seen_phrases[norm] = cid

        intent = _parse_cut_intent(clip)
        if intent is None:
            warnings.append(
                {
                    "code": "missing_cut_intent",
                    "severity": "info",
                    "clip_id": cid,
                    "message": "Speech clip has no cut_intent (older plan).",
                }
            )
        else:
            start_k = intent.get("start")
            end_k = intent.get("end")
            reason = str(intent.get("reason") or "").strip()
            if start_k in ("fragment", "abrupt") and not reason:
                warnings.append(
                    {
                        "code": "fragment_without_reason",
                        "severity": "warning",
                        "clip_id": cid,
                        "message": "Fragment start lacks a reason.",
                    }
                )
            if end_k in ("fragment", "abrupt") and not reason:
                warnings.append(
                    {
                        "code": "fragment_without_reason",
                        "severity": "warning",
                        "clip_id": cid,
                        "message": "Fragment end lacks a reason.",
                    }
                )

        w_start = _boundary_word(words, si, edge="start")
        w_end = _boundary_word(words, so, edge="end")
        if w_start and _token(str(w_start.get("word") or "")) in FUNCTION_OR_CONNECTIVE_END:
            if not (intent and intent.get("start") == "fragment" and intent.get("reason")):
                warnings.append(
                    {
                        "code": "starts_on_function_word",
                        "severity": "warning",
                        "clip_id": cid,
                        "message": f"Starts on function word {w_start.get('word')!r}.",
                    }
                )
        if w_end and _token(str(w_end.get("word") or "")) in FUNCTION_OR_CONNECTIVE_END:
            if not (intent and intent.get("end") in ("fragment", "abrupt", "fade") and intent.get("reason")):
                warnings.append(
                    {
                        "code": "ends_on_function_word",
                        "severity": "warning",
                        "clip_id": cid,
                        "message": f"Ends on function word {w_end.get('word')!r}.",
                        "suggested_source_out": float(w_end["start"]),
                    }
                )

        # low falloff at out-point while more speech follows in source
        path = _resolve_source(str(clip.get("source") or ""), root)
        if path and w_end:
            units_doc = load_json(speech_units_path(path))
            if not units_doc:
                units_doc = build_speech_units(path)
            unit = None
            for u in units_doc.get("phrases") or []:
                if isinstance(u, dict) and float(u["start"]) <= si <= float(u["end"]):
                    unit = u
                    break
            after_words = _clip_words(root, str(clip.get("source")), so, so + 5)
            falloff = None
            if unit:
                falloff = unit.get("energy_falloff_last_200ms")
            if after_words and falloff is not None and float(falloff) < 0.15:
                if not (intent and intent.get("end") in ("fragment", "abrupt") and intent.get("reason")):
                    warnings.append(
                        {
                            "code": "cut_during_flow",
                            "severity": "warning",
                            "clip_id": cid,
                            "message": "Out-point sits in continued speech flow (low energy falloff).",
                        }
                    )

        is_last = i == len(clips) - 1
        if is_last and w_end:
            terminal = str(w_end.get("word") or "").rstrip().endswith((".", "!", "?"))
            flagged_end = _token(str(w_end.get("word") or "")) in FUNCTION_OR_CONNECTIVE_END
            if intent and intent.get("end") == "complete" and (flagged_end or not terminal):
                warnings.append(
                    {
                        "code": "final_speech_hangs",
                        "severity": "warning",
                        "clip_id": cid,
                        "message": "Final speech clip claims a complete end but lands mid-thought.",
                    }
                )

    if speech_end > last_video_end + 0.08:
        warnings.append(
            {
                "code": "video_shorter_than_speech",
                "severity": "warning",
                "clip_id": None,
                "message": "Picture ends before the last audible speech.",
            }
        )

    return warnings


def readback_script_text(blocks: list[dict]) -> str:
    lines: list[str] = []
    for b in blocks:
        intent = b.get("cut_intent") or {}
        lines.append(
            f"[{b.get('clip_id')}] "
            f"(start={intent.get('start')}, end={intent.get('end')}"
            + (f", reason={intent.get('reason')!r}" if intent.get("reason") else "")
            + f"): {b.get('text')}"
        )
    return "\n".join(lines)
