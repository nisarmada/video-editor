"""
540p proxy videos and JPEG thumbnails for editor preview (cached under index/).
"""

from __future__ import annotations

from pathlib import Path

from media import clip_metadata, run_ffmpeg, video_duration_seconds

PROXY_HEIGHT = 540
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


def proxies_dir(root: Path) -> Path:
    path = root / "index" / "proxies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbnails_dir(root: Path) -> Path:
    path = root / "index" / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def proxy_path_for_clip(root: Path, clip_path: Path) -> Path:
    return proxies_dir(root) / f"{clip_path.stem}_540p.mp4"


def thumbnail_path_for_clip(root: Path, clip_path: Path) -> Path:
    return thumbnails_dir(root) / f"{clip_path.stem}.jpg"


def list_footage_files(root: Path) -> list[Path]:
    footage = root / "footage"
    if not footage.is_dir():
        return []
    return sorted(
        p
        for p in footage.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def proxy_is_fresh(source: Path, proxy: Path) -> bool:
    if not proxy.is_file():
        return False
    return proxy.stat().st_mtime >= source.stat().st_mtime


def thumbnail_is_fresh(source: Path, thumb: Path) -> bool:
    if not thumb.is_file():
        return False
    return thumb.stat().st_mtime >= source.stat().st_mtime


def _scale_filter(rotation: int | None) -> str:
    from media import rotation_filter

    rot = rotation_filter(rotation)
    return f"{rot}scale=-2:{PROXY_HEIGHT},format=yuv420p"


def ensure_proxy(root: Path, clip_path: Path, *, force: bool = False) -> Path:
    """Create or reuse a 540p H.264 proxy for one footage file."""
    source = clip_path if clip_path.is_absolute() else root / clip_path
    if not source.is_file():
        raise FileNotFoundError(f"Footage not found: {source}")

    out = proxy_path_for_clip(root, source)
    if not force and proxy_is_fresh(source, out):
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    _duration, _has_audio, rotation = clip_metadata(source)
    vf = _scale_filter(rotation)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run_ffmpeg(cmd)
    return out


def ensure_thumbnail(root: Path, clip_path: Path, *, force: bool = False) -> Path:
    """JPEG poster frame (cached)."""
    source = clip_path if clip_path.is_absolute() else root / clip_path
    if not source.is_file():
        raise FileNotFoundError(f"Footage not found: {source}")

    out = thumbnail_path_for_clip(root, source)
    if not force and thumbnail_is_fresh(source, out):
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        duration = video_duration_seconds(source)
    except RuntimeError:
        duration = 0.0
    t = min(1.0, max(0.0, duration / 2))

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(t),
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(out),
    ]
    run_ffmpeg(cmd)
    return out


def footage_entry(root: Path, clip_path: Path) -> dict:
    """Metadata for API list (does not build proxies)."""
    rel = f"footage/{clip_path.name}"
    proxy = proxy_path_for_clip(root, clip_path)
    thumb = thumbnail_path_for_clip(root, clip_path)
    try:
        duration = video_duration_seconds(clip_path)
    except RuntimeError:
        duration = None

    return {
        "name": clip_path.name,
        "source": rel,
        "duration_seconds": duration,
        "has_proxy": proxy.is_file(),
        "has_thumbnail": thumb.is_file(),
        "proxy_url": f"/api/footage/{clip_path.name}/proxy",
        "thumbnail_url": f"/api/footage/{clip_path.name}/thumbnail",
    }
