"""Load and format style profiles (plans/styles/<id>.json) for the planner."""

from __future__ import annotations

import json
import re
from pathlib import Path


def style_profile_path(root: Path, style_id: str) -> Path:
    sid = _validate_style_id(style_id)
    return (root / "plans" / "styles" / f"{sid}.json").resolve()


def _validate_style_id(style_id: str) -> str:
    raw = (style_id or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError("Invalid style id")
    if not re.match(r"^[a-zA-Z0-9._-]+$", raw):
        raise ValueError("Invalid style id")
    return raw


def slug_style_id(raw: str | None, fallback: str = "style") -> str:
    """Turn arbitrary user text into a safe filename stem (plans/styles/<id>.json)."""
    base = (raw or "").strip() or fallback
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("._-") or fallback
    return _validate_style_id(slug)


def load_style_profile(root: Path, style_id: str) -> dict:
    path = style_profile_path(root, style_id)
    if not path.is_file():
        raise FileNotFoundError(f"Style profile not found: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Style profile must be a JSON object")
    return data


def list_style_profiles(styles_dir: Path, root: Path) -> list[dict[str, str]]:
    if not styles_dir.is_dir():
        return []
    out: list[dict[str, str]] = []
    root = root.resolve()
    for f in sorted(styles_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("style_id") or f.stem)
        name = str(data.get("style_name") or sid)
        try:
            rel = str(f.resolve().relative_to(root))
        except ValueError:
            rel = str(f.name)
        out.append({"id": sid, "name": name, "path": rel})
    return out


def format_style_for_prompt(label: str, profile: dict) -> str:
    """Human-readable block for Claude system prompt."""
    lines: list[str] = [f"=== Reference style ({label}) ==="]
    name = profile.get("style_name") or profile.get("style_id") or label
    lines.append(f"Name: {name}")
    dur = profile.get("duration_seconds")
    if isinstance(dur, (int, float)):
        lines.append(f"Reference duration: {float(dur):.2f}s")

    cuts = profile.get("cuts") if isinstance(profile.get("cuts"), dict) else {}
    if cuts:
        sl = cuts.get("shot_length_seconds") or {}
        lines.append(
            "Cut pacing: "
            f"shots={cuts.get('shot_count')}, hard_cuts={cuts.get('hard_cut_count')}, "
            f"cuts/min≈{cuts.get('cuts_per_minute')} | "
            f"shot length p25–p75: {sl.get('p25')}–{sl.get('p75')}s "
            f"(mean {sl.get('mean')}s, max {sl.get('max')}s)."
        )

    speech = profile.get("speech") if isinstance(profile.get("speech"), dict) else {}
    if speech:
        lines.append(
            "Speech: "
            f"words≈{speech.get('word_count')}, "
            f"~{speech.get('words_per_minute')} WPM, "
            f"density≈{speech.get('speech_density')}."
        )

    vis = profile.get("visual_aesthetics")
    if isinstance(vis, dict):
        for k in (
            "editing_mood",
            "text_overlay_placement",
            "zoom_style",
            "pacing_feel",
            "notes",
        ):
            v = vis.get(k)
            if v:
                lines.append(f"{k}: {v}")

    pc = profile.get("planner_constraints")
    if isinstance(pc, dict):
        im = pc.get("imitate") or []
        av = pc.get("avoid") or []
        if isinstance(im, list) and im:
            lines.append("Rules to IMITATE when the user asks to match this style:")
            for r in im:
                lines.append(f"  - {r}")
        if isinstance(av, list) and av:
            lines.append("Rules to AVOID when the user asks to diverge from this style:")
            for r in av:
                lines.append(f"  - {r}")
    return "\n".join(lines)
