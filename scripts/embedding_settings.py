"""Embedding method for catalog ranking (index/app_settings.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "method": "hash",
    "model_name": "all-MiniLM-L6-v2",
}

VALID_METHODS = frozenset({"hash", "sentence_transformer"})


def _settings_path(root: Path | None) -> Path:
    base = root if root is not None else Path.cwd()
    return base / "index" / "app_settings.json"


def load_embedding_settings(root: Path | None = None) -> dict[str, Any]:
    path = _settings_path(root)
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    block = data.get("embedding")
    if not isinstance(block, dict):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    method = str(block.get("method") or "hash").lower()
    if method in VALID_METHODS:
        out["method"] = method
    name = str(block.get("model_name") or DEFAULTS["model_name"]).strip()
    if name:
        out["model_name"] = name
    return out
