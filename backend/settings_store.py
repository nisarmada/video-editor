"""Persist app settings (API keys, defaults) under index/ — never log secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SETTINGS_NAME = "app_settings.json"


def settings_path(root: Path) -> Path:
    return root / "index" / SETTINGS_NAME


def load_raw(root: Path) -> dict[str, Any]:
    path = settings_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_raw(root: Path, data: dict[str, Any]) -> None:
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def get_public_settings(root: Path) -> dict[str, Any]:
    """Safe subset for GET /api/settings (no secrets)."""
    raw = load_raw(root)
    key = raw.get("planner_api_key")
    configured = bool(
        isinstance(key, str) and len(key.strip()) > 0
    ) or bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    paths = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
    render_defaults = (
        raw.get("render_defaults")
        if isinstance(raw.get("render_defaults"), dict)
        else {}
    )
    ucs = raw.get("user_caption_styles")
    user_presets: list[dict[str, Any]] = []
    if isinstance(ucs, list):
        for item in ucs:
            if isinstance(item, dict) and item.get("id"):
                user_presets.append(item)
    kb = raw.get("keybindings")
    keybindings: dict[str, Any] = {}
    if isinstance(kb, dict):
        keybindings = kb
    ui = raw.get("ui")
    ui_public: dict[str, Any] = {}
    if isinstance(ui, dict):
        ui_public = ui
    acr = raw.get("audio_cut_refine")
    audio_cut_refine: dict[str, Any] = {}
    if isinstance(acr, dict):
        audio_cut_refine = acr
    return {
        "planner_api_key_configured": configured,
        "paths": {
            "footage": str(paths.get("footage", "footage")),
            "plans": str(paths.get("plans", "plans")),
            "output": str(paths.get("output", "output")),
        },
        "render_defaults": {
            "captions": bool(render_defaults.get("captions", False)),
            "max_length": render_defaults.get("max_length"),
            "video_crf": int(render_defaults.get("video_crf", 23))
            if render_defaults.get("video_crf") is not None
            else 23,
        },
        "user_caption_styles": user_presets,
        "keybindings": keybindings,
        "ui": ui_public,
        "audio_cut_refine": audio_cut_refine,
    }


def set_planner_api_key(root: Path, api_key: str | None) -> None:
    raw = load_raw(root)
    if api_key is None or (isinstance(api_key, str) and not api_key.strip()):
        raw.pop("planner_api_key", None)
    else:
        raw["planner_api_key"] = api_key.strip()
    save_raw(root, raw)


def merge_settings(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    raw = load_raw(root)
    if "planner_api_key" in body:
        v = body["planner_api_key"]
        if v is None or v == "":
            raw.pop("planner_api_key", None)
        elif isinstance(v, str):
            raw["planner_api_key"] = v.strip()
    if "paths" in body and isinstance(body["paths"], dict):
        raw.setdefault("paths", {})
        for k in ("footage", "plans", "output"):
            if k in body["paths"] and isinstance(body["paths"][k], str):
                raw["paths"][k] = body["paths"][k].strip()
    if "render_defaults" in body and isinstance(body["render_defaults"], dict):
        raw.setdefault("render_defaults", {})
        rd = body["render_defaults"]
        if "captions" in rd:
            raw["render_defaults"]["captions"] = bool(rd["captions"])
        if "max_length" in rd:
            ml = rd["max_length"]
            raw["render_defaults"]["max_length"] = (
                float(ml) if ml is not None else None
            )
        if "video_crf" in rd and rd["video_crf"] is not None:
            try:
                raw["render_defaults"]["video_crf"] = max(
                    0, min(int(rd["video_crf"]), 51)
                )
            except (TypeError, ValueError):
                pass
    if "user_caption_styles" in body and isinstance(body["user_caption_styles"], list):
        raw["user_caption_styles"] = body["user_caption_styles"]
    if "keybindings" in body:
        kb = body["keybindings"]
        if kb is None:
            raw.pop("keybindings", None)
        elif isinstance(kb, dict):
            raw["keybindings"] = kb
    if "ui" in body:
        u = body["ui"]
        if u is None:
            raw.pop("ui", None)
        elif isinstance(u, dict):
            prev = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
            merged = {**prev, **u}
            raw["ui"] = merged
    if "audio_cut_refine" in body:
        acr = body["audio_cut_refine"]
        if acr is None:
            raw.pop("audio_cut_refine", None)
        elif isinstance(acr, dict):
            prev = (
                raw.get("audio_cut_refine")
                if isinstance(raw.get("audio_cut_refine"), dict)
                else {}
            )
            raw["audio_cut_refine"] = {**prev, **acr}
    save_raw(root, raw)
    return get_public_settings(root)


def effective_planner_api_key(root: Path) -> str | None:
    """Env wins over file (dotenv may have loaded env)."""
    env_k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_k:
        return env_k
    raw = load_raw(root)
    k = raw.get("planner_api_key")
    if isinstance(k, str) and k.strip():
        return k.strip()
    return None


def effective_render_defaults(root: Path) -> dict[str, Any]:
    raw = load_raw(root)
    rd = raw.get("render_defaults") if isinstance(raw.get("render_defaults"), dict) else {}
    ml = rd.get("max_length")
    crf_raw = rd.get("video_crf", 23)
    try:
        crf = max(0, min(int(crf_raw), 51))
    except (TypeError, ValueError):
        crf = 23
    return {
        "captions": bool(rd.get("captions", False)),
        "max_length": float(ml) if isinstance(ml, (int, float)) else None,
        "video_crf": crf,
    }
