"""Preflight counts and cost estimates for footage analysis (incl. paid frame captions)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
import sys

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from index_cache import keyframes_path, load_json  # noqa: E402
from planner_limits import estimate_cost_usd  # noqa: E402

from backend.media_catalog import COMPLETE, build_media_catalog  # noqa: E402
from backend.settings_store import load_raw  # noqa: E402

AnalyzeMissingMode = Literal["all", "free_only"]

# Rough vision Haiku estimate per clip (one API call batches all keyframe images).
_BASE_INPUT_TOKENS = 900
_TOKENS_PER_KEYFRAME_IMAGE = 480
_OUTPUT_TOKENS_PER_FRAME = 90
_OUTPUT_TOKEN_FLOOR = 320


def _keyframe_count(root: Path, basename: str) -> int:
    clip = root / "footage" / basename
    if not clip.is_file():
        return 1
    doc = load_json(keyframes_path(clip))
    if not isinstance(doc, dict):
        return 1
    kfs = doc.get("keyframes")
    if isinstance(kfs, list) and kfs:
        return len(kfs)
    return 1


def _needs_paid_captions(entry: dict[str, Any]) -> bool:
    if entry.get("kind") != "video":
        return False
    analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
    cap = analysis.get("ai_frame_captions")
    return cap != COMPLETE


def _estimate_caption_cost_usd(keyframe_count: int) -> float:
    n = max(1, keyframe_count)
    input_tok = _BASE_INPUT_TOKENS + n * _TOKENS_PER_KEYFRAME_IMAGE
    output_tok = max(_OUTPUT_TOKEN_FLOOR, n * _OUTPUT_TOKENS_PER_FRAME)
    return round(estimate_cost_usd(input_tok, output_tok, tier="triage"), 4)


def get_remembered_analyze_mode(root: Path) -> AnalyzeMissingMode | None:
    raw = load_raw(root)
    analysis = raw.get("analysis")
    if not isinstance(analysis, dict):
        return None
    mode = analysis.get("remember_missing_mode")
    if mode in ("all", "free_only"):
        return mode
    return None


def build_analyze_preflight(
    root: Path,
    *,
    basenames: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize missing local steps and optional paid caption work."""
    entries, _warnings = build_media_catalog(
        root,
        scope="selected" if basenames else "all",
        only_basenames=basenames,
    )

    free_fields_video = [
        "merged_index",
        "transcript",
        "silences",
        "audio_perception",
        "takes",
        "shots",
        "video_perception",
        "keyframes",
    ]
    free_fields_audio = [
        "merged_index",
        "transcript",
        "silences",
        "audio_perception",
        "takes",
    ]

    file_rows: list[dict[str, Any]] = []
    paid_files: list[str] = []
    total_keyframes = 0
    est_cost = 0.0

    for entry in entries:
        eid = str(entry.get("id") or "")
        kind = entry.get("kind")
        analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
        fields = free_fields_audio if kind == "audio" else free_fields_video
        missing_free = [
            f
            for f in fields
            if analysis.get(f) != COMPLETE
        ]
        wf = analysis.get("waveform_peaks")
        wf_status = wf.get("status") if isinstance(wf, dict) else None
        if wf_status != COMPLETE:
            missing_free.append("waveform_peaks")

        needs_paid = _needs_paid_captions(entry)
        kf = _keyframe_count(root, eid) if needs_paid and kind == "video" else 0
        if needs_paid and kind == "video":
            paid_files.append(eid)
            total_keyframes += kf
            est_cost += _estimate_caption_cost_usd(kf)

        file_rows.append(
            {
                "id": eid,
                "missing_free": missing_free,
                "needs_paid_captions": needs_paid,
                "keyframe_count": kf,
            }
        )

    missing_free_any = [r for r in file_rows if r["missing_free"]]
    remember = get_remembered_analyze_mode(root)

    return {
        "files": file_rows,
        "free_missing_file_count": len(missing_free_any),
        "paid_caption_file_count": len(paid_files),
        "total_keyframes": total_keyframes,
        "haiku_calls": len(paid_files),
        "est_cost_usd": round(est_cost, 4),
        "caption_model": "claude-haiku-4-5-20251001",
        "remember_missing_mode": remember,
    }
