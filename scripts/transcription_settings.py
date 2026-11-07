"""Read transcription options from index/app_settings.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULTS = {
    "model_size": "small",
    "keep_quiet_speech": False,
}


def _settings_path(root: Path | None) -> Path:
    base = root if root is not None else Path.cwd()
    return base / "index" / "app_settings.json"


def load_transcription_settings(root: Path | None = None) -> dict[str, Any]:
    path = _settings_path(root)
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    block = data.get("transcription")
    if not isinstance(block, dict):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    size = str(block.get("model_size") or "small").lower()
    if size in ("small", "medium"):
        out["model_size"] = size
    out["keep_quiet_speech"] = bool(block.get("keep_quiet_speech"))
    return out
