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
    silences_path,
    shots_path,
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

        transcript_segments: list[Any]
        if tr_status == COMPLETE:
            segs = tr_doc.get("segments") if isinstance(tr_doc, dict) else []
            transcript_segments = segs if isinstance(segs, list) else []
            if not transcript_segments:
                transcript_segments = [{"note": "no speech detected"}]
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
                "waveform_peaks": _waveform_summary(clip_path),
            },
            "transcript_segments": transcript_segments,
            "silences": silences_list,
            "silence_ratio_estimate": sil_ratio,
            "shots": shots_raw if kind == "video" else [],
            "keyframes": kf_raw if kind == "video" else [],
            "ai_frame_captions": (caps.get("frames") if isinstance(caps, dict) else [])
            if kind == "video"
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
