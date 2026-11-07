"""Footage upload helpers: safe names, plan references, ffprobe validation."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Shared with scripts/footage_exts.py (import after path fix for tests)
_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from footage_exts import AUDIO_EXTS, FOOTAGE_EXTS, VIDEO_EXTS  # noqa: E402

_MAX_BASE_LEN = 180


def video_extension_allowed(name: str) -> bool:
    """Whether basename is allowed under footage/ (video + standalone audio)."""
    return Path(name).suffix.lower() in FOOTAGE_EXTS


def is_audio_only_ext(name: str) -> bool:
    return Path(name).suffix.lower() in AUDIO_EXTS


def sanitize_upload_basename(original: str) -> str:
    """Single filename segment, no path; ASCII safe subset."""
    base = Path(original).name
    if not base or base != Path(base).name:
        raise ValueError("Invalid filename")
    # Strip weird chars; keep extension
    stem = Path(base).stem
    ext = Path(base).suffix.lower()
    if ext not in FOOTAGE_EXTS:
        raise ValueError(
            f"Unsupported extension (allowed: {sorted(FOOTAGE_EXTS)})"
        )
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


def ffprobe_validate_media(path: Path) -> None:
    """Video files need a video stream; standalone audio needs an audio stream."""
    ext = path.suffix.lower()
    cmd_base = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)]
    r = subprocess.run(cmd_base, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffprobe failed")
    types = {(line or "").strip().lower() for line in (r.stdout or "").splitlines() if line.strip()}
    if ext in AUDIO_EXTS:
        if "audio" not in types:
            raise RuntimeError("File has no audio stream")
        return
    if ext in VIDEO_EXTS:
        if "video" not in types:
            raise RuntimeError("File has no video stream")
        return
    raise RuntimeError(f"Unknown media extension: {ext}")


def ffprobe_validate_video(path: Path) -> None:
    """Backward-compatible name for video-only checks."""
    ffprobe_validate_media(path)


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
