"""Paths for bundled fonts (OFL). Preset JSON lives in backend/caption_presets/."""

from __future__ import annotations

from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent


def fonts_bundle_dir() -> Path:
    return _BACKEND_DIR / "fonts"
