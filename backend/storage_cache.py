"""Disk usage for regenerable index caches and safe cleanup."""

from __future__ import annotations

import shutil
from pathlib import Path

REGENERABLE_SUFFIXES = (
    "_embed.json",
    "_perception.json",
    "_audio_perception.json",
    "_takes.json",
)

PAID_CAPTION_SUFFIX = "_captions.json"


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def storage_stats(root: Path) -> dict:
    index = root / "index"
    perception = index / "perception"
    keyframes = index / "keyframes"
    embed_bytes = 0
    if index.is_dir():
        for f in index.iterdir():
            if f.is_file() and f.name.endswith("_embed.json"):
                try:
                    embed_bytes += f.stat().st_size
                except OSError:
                    pass
    return {
        "perception_images_bytes": _dir_size(perception),
        "keyframes_images_bytes": _dir_size(keyframes),
        "embedding_json_bytes": embed_bytes,
        "paid_caption_json_bytes": caption_cache_bytes(root),
        "total_regenerable_bytes": (
            _dir_size(perception) + _dir_size(keyframes) + embed_bytes
        ),
    }


def clear_regenerable_caches(root: Path) -> dict:
    """Remove vision JPEG folders and cached JSON that analysis can rebuild."""
    index = root / "index"
    removed_files = 0
    freed = 0

    for sub in ("perception", "keyframes"):
        path = index / sub
        if path.is_dir():
            sz = _dir_size(path)
            shutil.rmtree(path, ignore_errors=True)
            freed += sz

    if index.is_dir():
        for f in list(index.iterdir()):
            if not f.is_file():
                continue
            if f.suffix == ".json" and any(
                f.name.endswith(suf) for suf in REGENERABLE_SUFFIXES
            ):
                try:
                    freed += f.stat().st_size
                    f.unlink(missing_ok=True)
                    removed_files += 1
                except OSError:
                    pass

    return {
        "removed_files": removed_files,
        "freed_bytes": freed,
        "stats": storage_stats(root),
    }


def caption_cache_bytes(root: Path) -> int:
    index = root / "index"
    total = 0
    if not index.is_dir():
        return 0
    for f in index.iterdir():
        if f.is_file() and f.name.endswith(PAID_CAPTION_SUFFIX):
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def clear_paid_caption_caches(root: Path) -> dict:
    """Remove AI frame caption JSON only (paid API to regenerate)."""
    index = root / "index"
    removed_files = 0
    freed = 0
    if index.is_dir():
        for f in list(index.iterdir()):
            if f.is_file() and f.name.endswith(PAID_CAPTION_SUFFIX):
                try:
                    freed += f.stat().st_size
                    f.unlink(missing_ok=True)
                    removed_files += 1
                except OSError:
                    pass
    stats = storage_stats(root)
    stats["paid_caption_json_bytes"] = caption_cache_bytes(root)
    return {
        "removed_files": removed_files,
        "freed_bytes": freed,
        "stats": stats,
    }
