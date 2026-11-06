"""Footage upload helpers: safe names, plan references, ffprobe validation."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# Keep in sync with scripts/proxy_media.VIDEO_EXTS
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}

_MAX_BASE_LEN = 180


def video_extension_allowed(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXTS


def sanitize_upload_basename(original: str) -> str:
    """Single filename segment, no path; ASCII safe subset."""
    base = Path(original).name
    if not base or base != Path(base).name:
        raise ValueError("Invalid filename")
    # Strip weird chars; keep extension
    stem = Path(base).stem
    ext = Path(base).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise ValueError(f"Unsupported extension (allowed: {sorted(VIDEO_EXTS)})")
    stem_clean = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-")
    if not stem_clean:
        stem_clean = "clip"
    if len(stem_clean) > _MAX_BASE_LEN:
        stem_clean = stem_clean[:_MAX_BASE_LEN]
    return f"{stem_clean}{ext}"


def unique_footage_path(footage_dir: Path, basename: str) -> tuple[Path, str]:
    """Return (path, final_basename). Auto-rename on collision (stem_2.ext)."""
    base = Path(basename).name
    if base != basename or ".." in base or "/" in base or "\\" in base:
        raise ValueError("Invalid path")
    target = footage_dir / base
    if not target.exists():
        return target, base
    stem = target.stem
    ext = target.suffix
    n = 2
    while n < 10000:
        candidate = f"{stem}_{n}{ext}"
        p = footage_dir / candidate
        if not p.exists():
            return p, candidate
        n += 1
    raise ValueError("Could not find a free filename")


def ffprobe_validate_video(path: Path) -> None:
    """Require at least one video stream via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffprobe failed")
    out = (r.stdout or "").strip().lower()
    if "video" not in out:
        raise RuntimeError("File has no video stream")


def iter_plan_sources(plan_data: object) -> list[str]:
    """Collect clip source strings from v2 timeline dict."""
    out: list[str] = []
    if not isinstance(plan_data, dict):
        return out
    if plan_data.get("schema_version") != 2:
        return out
    for track in plan_data.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict):
                s = clip.get("source")
                if isinstance(s, str):
                    out.append(s)
    return out


def plans_referencing_footage(plans_dir: Path, footage_rel: str) -> list[str]:
    """Return plan stems (no .json) that reference footage_rel e.g. footage/foo.mp4."""
    if not plans_dir.is_dir():
        return []
    hits: list[str] = []
    for f in sorted(plans_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sources = iter_plan_sources(data)
        if footage_rel in sources:
            hits.append(f.stem)
    return hits
