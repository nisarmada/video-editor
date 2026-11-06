"""Built-in presets + merging plan settings.caption_style and per-segment overrides."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_PRESETS_DIR = _ROOT / "backend" / "caption_presets"
_FONTS_DIR = _ROOT / "backend" / "fonts"


def fonts_bundle_dir() -> Path:
    return _FONTS_DIR


@lru_cache(maxsize=1)
def load_builtin_presets() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not _PRESETS_DIR.is_dir():
        return out
    for p in sorted(_PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        pid = data.get("id")
        if isinstance(pid, str) and pid:
            out[pid] = data
    return out


def get_builtin_preset(preset_id: str) -> dict[str, Any] | None:
    return load_builtin_presets().get(preset_id)


def list_builtin_presets() -> list[dict[str, Any]]:
    return sorted(load_builtin_presets().values(), key=lambda x: str(x.get("name", x.get("id", ""))))


def merge_style_dict(
    base: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    out = dict(base)
    if not override:
        return out
    for k, v in override.items():
        if k in ("id", "name", "preset"):
            continue
        if v is not None:
            out[k] = v
    return out


def default_caption_style() -> dict[str, Any]:
    p = get_builtin_preset("bold_pop")
    if p:
        return dict(p)
    return {
        "preset": "bold_pop",
        "font_family": "Arial",
        "font_size": 0.04,
        "bold": True,
        "italic": False,
        "uppercase": False,
        "text_color": "#FFFFFF",
        "active_word_color": "#FFFF00",
        "outline_color": "#000000",
        "outline_width": 3.0,
        "shadow_color": "#000000",
        "shadow_offset": [2, 2],
        "box_color": "#000000",
        "box_opacity": 0.0,
        "box_padding": 4.0,
        "position_y": 78.0,
        "max_words_per_line": 3,
        "max_lines": 3,
        "line_spacing": 1.1,
        "animation": "word_highlight",
        "animation_intensity": 0.8,
        "active_word_scale": 1.15,
    }


def resolve_merged_style_for_plan(plan_data: dict[str, Any] | None) -> dict[str, Any]:
    """Merge built-in preset + plan settings.caption_style."""
    builtin = default_caption_style()
    if not plan_data or not isinstance(plan_data, dict):
        return builtin
    settings = plan_data.get("settings")
    if not isinstance(settings, dict):
        return builtin
    cs = settings.get("caption_style")
    if not isinstance(cs, dict):
        return builtin
    pid = cs.get("preset") or builtin.get("preset") or "bold_pop"
    preset = get_builtin_preset(str(pid)) if isinstance(pid, str) else None
    base = dict(preset) if preset else dict(builtin)
    skip = {"preset", "id", "name"}
    for k, v in cs.items():
        if k in skip:
            continue
        if v is not None:
            base[k] = v
    return base


def style_for_segment(
    plan_merged: dict[str, Any],
    seg: dict[str, Any],
) -> dict[str, Any]:
    ovr = seg.get("style_override")
    if isinstance(ovr, dict):
        return merge_style_dict(plan_merged, ovr)
    return dict(plan_merged)
