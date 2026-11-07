"""
Unified per-file media catalog for AI planning (video, audio-only, video without audio).
Same field shape for every file; missing analysis is explicit (never silent omission).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
import sys

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from footage_exts import AUDIO_EXTS, VIDEO_EXTS  # noqa: E402
from index_cache import (  # noqa: E402
    captions_path,
    keyframes_path,
    load_json,
    merged_index_path,
    audio_perception_path,
    perception_path,
    silences_path,
    shots_path,
    takes_path,
    transcript_path,
    waveform_path,
)
from media import clip_metadata  # noqa: E402
from probe import get_video_info  # noqa: E402
from proxy_media import list_footage_files  # noqa: E402

NOT_ANALYZED = "not analyzed"
COMPLETE = "complete"


def _file_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return "unknown"


def _analysis_file_status(path: Path) -> str:
    """Whether a cached JSON artifact exists on disk."""
    return COMPLETE if path.is_file() else NOT_ANALYZED


def _takes_summary(doc: dict | None) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {"status": NOT_ANALYZED}
    if doc.get("has_audio") is False:
        return {"status": COMPLETE, "has_audio": False, "take_count": 0}
    if "has_speech" not in doc and doc.get("takes") is None:
        return {"status": NOT_ANALYZED}
    takes = doc.get("takes") if isinstance(doc.get("takes"), list) else []
    groups = doc.get("phrase_groups") if isinstance(doc.get("phrase_groups"), list) else []
    compact: list[dict[str, Any]] = []
    for row in takes:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "")
        compact.append(
            {
                "take_index": row.get("take_index"),
                "phrase_group": row.get("phrase_group"),
                "start": row.get("start"),
                "end": row.get("end"),
                "speech_rate_wpm": row.get("speech_rate_wpm"),
                "ends_complete_sentence": row.get("ends_complete_sentence"),
                "is_restart": row.get("is_restart"),
                "abandoned_sentence": row.get("abandoned_sentence"),
                "text_preview": text[:72] + ("…" if len(text) > 72 else ""),
            }
        )
    return {
        "status": COMPLETE,
        "has_speech": bool(doc.get("has_speech")),
        "take_count": len(takes),
        "phrase_group_count": len(groups),
        "takes_compact": compact,
    }


def _audio_perception_summary(doc: dict | None) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {"status": NOT_ANALYZED}
    if doc.get("has_audio") is False:
        return {"status": COMPLETE, "has_audio": False}
    if doc.get("has_audio") is not True and not doc.get("windows"):
        return {"status": NOT_ANALYZED}
    counts = doc.get("window_class_counts") if isinstance(doc.get("window_class_counts"), dict) else {}
    return {
        "status": COMPLETE,
        "has_audio": True,
        "loudness_lufs": doc.get("loudness_lufs"),
        "loudness_range_lu": doc.get("loudness_range_lu"),
        "dynamic_range_db": doc.get("dynamic_range_db"),
        "speech_rate_wpm": doc.get("speech_rate_wpm"),
        "filler_count": doc.get("filler_count"),
        "pause_ratio": doc.get("pause_ratio"),
        "longest_pause_s": doc.get("longest_pause_s"),
        "window_class_counts": counts,
    }


def _perception_summary(doc: dict | None) -> dict[str, Any]:
    """Roll shot-level numbers up for the catalog (no labels or verdicts)."""
    if not isinstance(doc, dict):
        return {"status": NOT_ANALYZED}
    shots = doc.get("shots") or []
    if not isinstance(shots, list) or not shots:
        return {"status": NOT_ANALYZED, "shot_count": 0}
    motion = [s.get("motion_level") for s in shots if isinstance(s, dict)]
    shake = [s.get("shake_score") for s in shots if isinstance(s, dict)]
    bright = [s.get("mean_brightness") for s in shots if isinstance(s, dict)]
    contrast = [s.get("contrast") for s in shots if isinstance(s, dict)]
    faces = [
        int(s.get("face_sample_hits") or 0) > 0
        for s in shots
        if isinstance(s, dict) and int(s.get("face_samples") or 0) > 0
    ]

    def _mean(nums: list) -> float | None:
        vals = [float(x) for x in nums if isinstance(x, (int, float))]
        return round(float(sum(vals) / len(vals)), 4) if vals else None

    return {
        "status": COMPLETE,
        "shot_count": len(shots),
        "mean_motion_level": _mean(motion),
        "mean_shake_score": _mean(shake),
        "mean_brightness": _mean(bright),
        "mean_contrast": _mean(contrast),
        "shots_with_face_samples": sum(1 for hit in faces if hit),
    }


def _silence_ratio(duration: float, silences: list[dict] | None) -> float | None:
    if duration <= 0 or not silences:
        return None
    silent = 0.0
    for s in silences:
        try:
            a, b = float(s["start"]), float(s["end"])
            silent += max(0.0, b - a)
        except (KeyError, TypeError, ValueError):
            continue
    return round(min(1.0, silent / duration), 4)


def _waveform_summary(clip_path: Path) -> dict[str, Any]:
    wp = waveform_path(clip_path)
    data = load_json(wp)
    if not isinstance(data, dict):
        return {"status": NOT_ANALYZED, "peak_buckets": None}
    peaks = data.get("peaks") or []
    n = len(peaks) if isinstance(peaks, list) else 0
    return {
        "status": COMPLETE if wp.is_file() else NOT_ANALYZED,
        "peak_buckets": n,
        "has_audio_in_waveform": bool(data.get("has_audio")),
    }


def build_media_catalog(
    root: Path,
    *,
    scope: str = "all",
    only_basenames: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    One entry per footage file. Returns (entries, warnings).

    scope: "all" = every file in footage/; "selected" = only_basenames (must be non-empty).
    """
    warnings: list[str] = []
    files = list_footage_files(root)
    if scope == "selected":
        if not only_basenames:
            raise ValueError("scope=selected requires only_basenames")
        want = {Path(n).name for n in only_basenames if n and str(n).strip()}
        files = [p for p in files if p.name in want]
        missing = sorted(want - {p.name for p in files})
        if missing:
            raise ValueError("These files are not in footage/: " + ", ".join(missing))

    entries: list[dict[str, Any]] = []
    for clip_path in files:
        name = clip_path.name
        kind = _file_kind(name)
        rel = f"footage/{name}"
        merged = merged_index_path(clip_path)
        merged_status = _analysis_file_status(merged)

        try:
            duration, has_audio, rotation = clip_metadata(clip_path)
        except (OSError, RuntimeError) as e:
            warnings.append(f"{name}: clip_metadata failed ({e})")
            duration, has_audio, rotation = 0.0, False, None

        has_video_stream = kind == "video"
        width: int | None = None
        height: int | None = None
        fps: float | None = None
        if kind == "video":
            try:
                probe = get_video_info(clip_path)
                for s in probe.get("streams") or []:
                    if s.get("codec_type") == "video":
                        width = s.get("width")
                        height = s.get("height")
                        fr = s.get("avg_frame_rate") or s.get("r_frame_rate")
                        if isinstance(fr, str) and "/" in fr:
                            a, b = fr.split("/", 1)
                            try:
                                fps = float(a) / float(b) if float(b) else None
                            except (TypeError, ValueError):
                                fps = None
                        break
            except (OSError, RuntimeError) as e:
                warnings.append(f"{name}: probe failed ({e})")

        # Prefer merged index for rich fields when present
        merged_data: dict[str, Any] = {}
        if merged.is_file():
            raw = load_json(merged)
            if isinstance(raw, dict):
                merged_data = raw

        tr_path = transcript_path(clip_path)
        tr_status = _analysis_file_status(tr_path)
        tr_doc = merged_data.get("transcript") if merged_data else None
        if not isinstance(tr_doc, dict):
            tr_doc = load_json(tr_path) or {}

        shots_raw = merged_data.get("shots")
        if shots_raw is None:
            sd = load_json(shots_path(clip_path))
            shots_raw = sd.get("shots", sd) if isinstance(sd, dict) else []

        kf_raw = merged_data.get("keyframes")
        if kf_raw is None:
            kd = load_json(keyframes_path(clip_path))
            kf_raw = kd.get("keyframes", kd) if isinstance(kd, dict) else []

        sil_raw = merged_data.get("silences")
        if sil_raw is None:
            sdoc = load_json(silences_path(clip_path))
            sil_raw = sdoc.get("silences", sdoc) if isinstance(sdoc, dict) else None

        caps = merged_data.get("captions") if merged_data else None
        if caps is None:
            caps = load_json(captions_path(clip_path))

        perception_doc = merged_data.get("perception") if merged_data else None
        if perception_doc is None:
            perception_doc = load_json(perception_path(clip_path))
        perception_summary = _perception_summary(
            perception_doc if isinstance(perception_doc, dict) else None
        )

        audio_doc = merged_data.get("audio_perception") if merged_data else None
        if audio_doc is None:
            audio_doc = load_json(audio_perception_path(clip_path))
        audio_summary = _audio_perception_summary(
            audio_doc if isinstance(audio_doc, dict) else None
        )

        takes_doc = merged_data.get("takes") if merged_data else None
        if takes_doc is None:
            takes_doc = load_json(takes_path(clip_path))
        takes_summary = _takes_summary(takes_doc if isinstance(takes_doc, dict) else None)

        transcript_segments: list[Any]
        transcript_words: list[dict[str, Any]] = []
        if tr_status == COMPLETE:
            segs = tr_doc.get("segments") if isinstance(tr_doc, dict) else []
            transcript_segments = segs if isinstance(segs, list) else []
            if not transcript_segments:
                transcript_segments = [{"note": "no speech detected"}]
            for seg in transcript_segments:
                if not isinstance(seg, dict):
                    continue
                for w in seg.get("words") or []:
                    if not isinstance(w, dict):
                        continue
                    try:
                        transcript_words.append(
                            {
                                "word": w.get("word"),
                                "start": round(float(w["start"]), 4),
                                "end": round(float(w["end"]), 4),
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
        else:
            transcript_segments = [{"note": NOT_ANALYZED}]

        silences_list: list[dict] = sil_raw if isinstance(sil_raw, list) else []
        sil_ratio = _silence_ratio(float(duration), silences_list)

        entry: dict[str, Any] = {
            "id": name,
            "source_path": rel,
            "kind": kind,
            "duration_seconds": round(float(duration), 6) if duration else 0.0,
            "has_video": bool(has_video_stream),
            "has_audio": bool(has_audio),
            "width": width,
            "height": height,
            "fps": round(fps, 4) if fps is not None else None,
            "rotation_degrees": rotation,
            "analysis": {
                "merged_index": merged_status,
                "transcript": tr_status,
                "silences": _analysis_file_status(silences_path(clip_path)),
                "shots": _analysis_file_status(shots_path(clip_path))
                if kind == "video"
                else "n/a (audio-only file)",
                "keyframes": _analysis_file_status(keyframes_path(clip_path))
                if kind == "video"
                else "n/a (audio-only file)",
                "ai_frame_captions": _analysis_file_status(captions_path(clip_path))
                if kind == "video"
                else "n/a (audio-only file)",
                "video_perception": _analysis_file_status(perception_path(clip_path))
                if kind == "video"
                else "n/a (audio-only file)",
                "audio_perception": _analysis_file_status(audio_perception_path(clip_path))
                if has_audio
                else "n/a (no audio)",
                "takes": _analysis_file_status(takes_path(clip_path))
                if has_audio
                else "n/a (no audio)",
                "waveform_peaks": _waveform_summary(clip_path),
            },
            "perception_summary": perception_summary if kind == "video" else None,
            "perception_shots": (
                perception_doc.get("shots")
                if isinstance(perception_doc, dict)
                else []
            )
            if kind == "video"
            else [],
            "transcript_segments": transcript_segments,
            "transcript_words": transcript_words,
            "silences": silences_list,
            "silence_ratio_estimate": sil_ratio,
            "shots": shots_raw if kind == "video" else [],
            "keyframes": kf_raw if kind == "video" else [],
            "ai_frame_captions": (caps.get("frames") if isinstance(caps, dict) else [])
            if kind == "video"
            else [],
            "audio_perception_summary": audio_summary if has_audio else None,
            "audio_perception_windows": (
                audio_doc.get("windows") if isinstance(audio_doc, dict) else []
            )
            if has_audio
            else [],
            "takes_summary": takes_summary if has_audio else None,
            "takes": (
                takes_doc.get("takes") if isinstance(takes_doc, dict) else []
            )
            if has_audio
            else [],
            "phrase_groups": (
                takes_doc.get("phrase_groups") if isinstance(takes_doc, dict) else []
            )
            if has_audio
            else [],
        }
        entries.append(entry)

    return entries, warnings


def list_unanalyzed_for_planning(root: Path, basenames: list[str] | None) -> list[str]:
    """Basenames missing merged index (needed for planner context)."""
    scope = "selected" if basenames else "all"
    entries, _ = build_media_catalog(
        root, scope=scope, only_basenames=basenames
    )
    out: list[str] = []
    for e in entries:
        st = (e.get("analysis") or {}).get("merged_index")
        if st != COMPLETE:
            out.append(e["id"])
    return out
