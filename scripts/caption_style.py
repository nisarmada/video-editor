"""
Caption style schema validation (shared with backend via import).
"""

from __future__ import annotations

from typing import Any

ANIMATIONS = frozenset(
    {
        "none",
        "word_highlight",
        "word_pop",
        "word_box",
        "karaoke_sweep",
        "typewriter",
        "bounce_in",
        "fade_in",
        "neon",
    }
)

COLOR_KEYS = ("text_color", "active_word_color", "outline_color", "shadow_color", "box_color")


def _hex6(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 7 or s[0] != "#":
        return False
    try:
        int(s[1:], 16)
    except ValueError:
        return False
    return True


def validate_caption_style_dict(d: dict[str, Any], label: str = "caption_style") -> list[str]:
    """Return list of human-readable errors; empty if ok."""
    errors: list[str] = []
    if not isinstance(d, dict):
        return [f"{label} must be an object."]

    ff = d.get("font_family")
    if ff is not None and (not isinstance(ff, str) or not ff.strip()):
        errors.append(f"{label}.font_family must be a non-empty string if set.")

    fs = d.get("font_size")
    if fs is not None:
        try:
            v = float(fs)
            if v <= 0 or v > 0.5:
                errors.append(f"{label}.font_size must be between 0 and 0.5 (fraction of video height).")
        except (TypeError, ValueError):
            errors.append(f"{label}.font_size must be a number.")

    for bkey in ("bold", "italic", "uppercase"):
        if bkey in d and not isinstance(d[bkey], bool):
            errors.append(f"{label}.{bkey} must be boolean.")

    for ck in COLOR_KEYS:
        if ck in d and d[ck] is not None:
            if not isinstance(d[ck], str) or not _hex6(d[ck]):
                errors.append(f"{label}.{ck} must be #RRGGBB.")

    ow = d.get("outline_width")
    if ow is not None:
        try:
            if float(ow) < 0:
                errors.append(f"{label}.outline_width must be >= 0.")
        except (TypeError, ValueError):
            errors.append(f"{label}.outline_width must be a number.")

    so = d.get("shadow_offset")
    if so is not None:
        if not isinstance(so, (list, tuple)) or len(so) != 2:
            errors.append(f"{label}.shadow_offset must be [x, y].")
        else:
            try:
                float(so[0])
                float(so[1])
            except (TypeError, ValueError):
                errors.append(f"{label}.shadow_offset must be numeric pairs.")

    bo = d.get("box_opacity")
    if bo is not None:
        try:
            v = float(bo)
            if v < 0 or v > 1:
                errors.append(f"{label}.box_opacity must be 0..1.")
        except (TypeError, ValueError):
            errors.append(f"{label}.box_opacity must be a number.")

    bp = d.get("box_padding")
    if bp is not None:
        try:
            if float(bp) < 0:
                errors.append(f"{label}.box_padding must be >= 0.")
        except (TypeError, ValueError):
            errors.append(f"{label}.box_padding must be a number.")

    py = d.get("position_y")
    if py is not None:
        try:
            v = float(py)
            if v < 0 or v > 100:
                errors.append(f"{label}.position_y must be 0..100 (percent from top).")
        except (TypeError, ValueError):
            errors.append(f"{label}.position_y must be a number.")

    mw = d.get("max_words_per_line")
    if mw is not None:
        try:
            n = int(mw)
            if n < 1 or n > 5:
                errors.append(f"{label}.max_words_per_line must be 1..5.")
        except (TypeError, ValueError):
            errors.append(f"{label}.max_words_per_line must be an integer.")

    ml = d.get("max_lines")
    if ml is not None:
        try:
            n = int(ml)
            if n < 1 or n > 5:
                errors.append(f"{label}.max_lines must be 1..5.")
        except (TypeError, ValueError):
            errors.append(f"{label}.max_lines must be an integer.")

    ls = d.get("line_spacing")
    if ls is not None:
        try:
            if float(ls) < 0:
                errors.append(f"{label}.line_spacing must be >= 0.")
        except (TypeError, ValueError):
            errors.append(f"{label}.line_spacing must be a number.")

    anim = d.get("animation")
    if anim is not None and anim not in ANIMATIONS:
        errors.append(f"{label}.animation must be one of: {', '.join(sorted(ANIMATIONS))}.")

    ai = d.get("animation_intensity")
    if ai is not None:
        try:
            v = float(ai)
            if v < 0 or v > 1:
                errors.append(f"{label}.animation_intensity must be 0..1.")
        except (TypeError, ValueError):
            errors.append(f"{label}.animation_intensity must be a number.")

    aws = d.get("active_word_scale")
    if aws is not None:
        try:
            v = float(aws)
            if v < 0.5 or v > 2.0:
                errors.append(f"{label}.active_word_scale should be between 0.5 and 2.0.")
        except (TypeError, ValueError):
            errors.append(f"{label}.active_word_scale must be a number.")

    pid = d.get("preset")
    if pid is not None and (not isinstance(pid, str) or not pid.strip()):
        errors.append(f"{label}.preset must be a non-empty string if set.")

    return errors


def validate_style_override(d: Any, label: str) -> list[str]:
    if d is None:
        return []
    if not isinstance(d, dict):
        return [f"{label} must be an object."]
    return validate_caption_style_dict(d, label=label)
