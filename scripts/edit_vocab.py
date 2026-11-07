"""
Shared edit-vocabulary helpers (fades, transitions, ducking) for export + validation.
"""

from __future__ import annotations

AUDIO_FADE_SECONDS = 0.02

# Overlap ducking ramps. frontend/src/timeline/duckEnvelope.ts uses the same numbers.
DUCK_ATTACK_S = 0.08
DUCK_RELEASE_S = 0.25
DUCK_GAIN_DEFAULT = 0.25

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


def merge_time_windows(
    windows: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Sort and merge overlapping [start, end) windows."""
    items = sorted((float(a), float(b)) for a, b in windows if float(b) - float(a) > 1e-4)
    if not items:
        return []
    merged: list[tuple[float, float]] = [items[0]]
    for start, end in items[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e + 1e-4:
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged


def _window_duck_factor(
    t: float,
    start: float,
    end: float,
    duck_gain: float,
    attack: float,
    release: float,
) -> float:
    """1 outside the window, duck_gain in the middle, linear attack and release."""
    span = end - start
    if span <= 1e-4:
        return 1.0
    if t < start or t >= end:
        return 1.0
    attack_s = min(max(attack, 0.0), span / 2)
    release_s = min(max(release, 0.0), max(span - attack_s, 0.0))
    if attack_s > 1e-4 and t < start + attack_s:
        return 1.0 + (duck_gain - 1.0) * ((t - start) / attack_s)
    if t < end - release_s:
        return duck_gain
    if release_s <= 1e-4:
        return duck_gain
    return duck_gain + (1.0 - duck_gain) * ((t - (end - release_s)) / release_s)


def duck_factor_at(
    t: float,
    windows: list[tuple[float, float]],
    duck_gain: float,
    *,
    attack: float = DUCK_ATTACK_S,
    release: float = DUCK_RELEASE_S,
) -> float:
    """Loudest reduction wins when several overlap windows are active."""
    factor = 1.0
    for start, end in merge_time_windows(windows):
        factor = min(
            factor,
            _window_duck_factor(t, start, end, duck_gain, attack, release),
        )
    return factor


def _fmt_s(value: float) -> str:
    return f"{value:.6f}"


def _window_duck_expr(
    start: float,
    end: float,
    duck_gain: float,
    attack: float,
    release: float,
) -> str:
    """FFmpeg expr matching _window_duck_factor. Commas stay inside the volume quotes."""
    span = end - start
    if span <= 1e-4:
        return "1"
    attack_s = min(max(attack, 0.0), span / 2)
    release_s = min(max(release, 0.0), max(span - attack_s, 0.0))
    gain = _fmt_s(duck_gain)
    start_s = _fmt_s(start)
    end_s = _fmt_s(end)
    attack_end = start + attack_s
    release_start = end - release_s
    if attack_s > 1e-4:
        attack_lerp = f"(1+({gain}-1)*(t-{start_s})/{_fmt_s(attack_s)})"
    else:
        attack_lerp = gain
        attack_end = start
    if release_s > 1e-4:
        release_lerp = (
            f"({gain}+(1-({gain}))*(t-{_fmt_s(release_start)})/{_fmt_s(release_s)})"
        )
    else:
        release_lerp = gain
        release_start = end
    return (
        f"if(lt(t,{start_s}),1,"
        f"if(lt(t,{_fmt_s(attack_end)}),{attack_lerp},"
        f"if(lt(t,{_fmt_s(release_start)}),{gain},"
        f"if(lt(t,{end_s}),{release_lerp},1))))"
    )


def ffmpeg_duck_volume_filter(
    base_volume: float,
    windows: list[tuple[float, float]],
    duck_gain: float,
    *,
    attack: float = DUCK_ATTACK_S,
    release: float = DUCK_RELEASE_S,
) -> str:
    """
    Volume filter that ducks only inside overlap windows.
    No windows → constant gain (old plans with no duck target stay a flat volume).
    """
    vol = float(base_volume)
    if vol <= 0:
        return "volume=0"
    merged = merge_time_windows(windows)
    if not merged:
        if abs(vol - 1.0) < 1e-9:
            return "volume=1"
        return f"volume={vol:.8f}"
    expr = _window_duck_expr(merged[0][0], merged[0][1], duck_gain, attack, release)
    for start, end in merged[1:]:
        expr = f"min({expr},{_window_duck_expr(start, end, duck_gain, attack, release)})"
    return f"volume=volume='{vol:.8f}*({expr})':eval=frame"


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
