"""
Shared edit-vocabulary helpers (fades, transitions, ducking) for export + validation.
"""

from __future__ import annotations

AUDIO_FADE_SECONDS = 0.02

TRANSITION_TYPES = frozenset({"dissolve", "crossfade"})


def _clip_fade_value(clip: dict, key: str) -> float | None:
    v = clip.get(key)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, f)


def audio_fades_for_segment(
    audio_fade_in: float | None,
    audio_fade_out: float | None,
    *,
    index: int,
    piece_count: int,
    seg_duration: float,
) -> tuple[float, float]:
    """
    Fade durations (seconds) on this segment's audio bus.
    Omitted clip fields → legacy concat boundary fades (20ms between pieces only).
    Explicit clip fields → per-clip fades (0 allowed).
    """
    explicit = audio_fade_in is not None or audio_fade_out is not None
    if explicit:
        fin = audio_fade_in if audio_fade_in is not None else 0.0
        fout = audio_fade_out if audio_fade_out is not None else 0.0
    else:
        fin = AUDIO_FADE_SECONDS if index > 0 else 0.0
        fout = AUDIO_FADE_SECONDS if index < piece_count - 1 else 0.0
    fin = min(fin, max(seg_duration * 0.5, 0.0))
    fout = min(fout, max(seg_duration * 0.5, 0.0))
    return fin, fout


def audio_fades_for_branch(
    audio_fade_in: float | None,
    audio_fade_out: float | None,
    *,
    wall_duration: float,
) -> tuple[float, float]:
    """Audio-track clips: default 20ms in+out on each clip when fields omitted."""
    explicit = audio_fade_in is not None or audio_fade_out is not None
    if explicit:
        fin = audio_fade_in if audio_fade_in is not None else 0.0
        fout = audio_fade_out if audio_fade_out is not None else 0.0
    else:
        fin = fout = AUDIO_FADE_SECONDS
    fin = min(fin, max(wall_duration * 0.5, 0.0))
    fout = min(fout, max(wall_duration * 0.5, 0.0))
    return fin, fout


def video_fade_chain(
    video_fade_in: float | None,
    video_fade_out: float | None,
    *,
    seg_duration: float,
) -> str:
    """ffmpeg fade filters on normalized video; empty if no explicit fades."""
    if video_fade_in is None and video_fade_out is None:
        return ""
    fin = video_fade_in if video_fade_in is not None else 0.0
    fout = video_fade_out if video_fade_out is not None else 0.0
    parts: list[str] = []
    if fin > 1e-6:
        parts.append(f"fade=t=in:st=0:d={min(fin, seg_duration):.6f}")
    if fout > 1e-6:
        st = max(seg_duration - fout, 0.0)
        parts.append(f"fade=t=out:st={st:.6f}:d={fout:.6f}")
    return ",".join(parts)


def append_audio_afade_filters(
    filters: list[str],
    *,
    seg_duration: float,
    fade_in: float,
    fade_out: float,
) -> None:
    if fade_in > 1e-6:
        filters.insert(0, f"afade=t=in:st=0:d={fade_in:.6f}")
    if fade_out > 1e-6:
        st = max(seg_duration - fade_out, 0.0)
        filters.append(f"afade=t=out:st={st:.6f}:d={fade_out:.6f}")


def validate_fade_fields(clip: dict, label: str, duration: float) -> list[str]:
    errs: list[str] = []
    half = max(duration * 0.5, 0.0)
    for key in (
        "audio_fade_in",
        "audio_fade_out",
        "video_fade_in",
        "video_fade_out",
    ):
        if key not in clip:
            continue
        try:
            v = float(clip[key])
        except (TypeError, ValueError):
            errs.append(f"{label}: {key} must be a number.")
            continue
        if v < 0:
            errs.append(f"{label}: {key} must be >= 0.")
        elif v > half + 0.001:
            errs.append(f"{label}: {key} {v:.3f}s exceeds half clip duration.")
    tr = clip.get("transition_out")
    if tr is not None:
        if not isinstance(tr, dict):
            errs.append(f"{label}: transition_out must be an object.")
        else:
            t = tr.get("type")
            if t not in TRANSITION_TYPES:
                errs.append(f"{label}: transition_out.type must be dissolve or crossfade.")
            try:
                d = float(tr.get("duration", 0))
            except (TypeError, ValueError):
                errs.append(f"{label}: transition_out.duration must be a number.")
                d = -1.0
            if d <= 0 or d > half + 0.001:
                errs.append(f"{label}: transition_out.duration out of range.")
    return errs
