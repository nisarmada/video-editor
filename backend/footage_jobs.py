"""Background proxy/thumbnail generation for footage files."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

_lock = threading.Lock()
# name (basename) -> None | dict with status processing|failed|ready cleanup
_jobs: dict[str, dict[str, Any]] = {}


def mark_processing(name: str) -> None:
    with _lock:
        _jobs[name] = {"status": "processing", "error": None}


def mark_failed(name: str, msg: str) -> None:
    with _lock:
        _jobs[name] = {"status": "failed", "error": msg}


def clear_job(name: str) -> None:
    with _lock:
        _jobs.pop(name, None)


def get_job(name: str) -> dict[str, Any] | None:
    with _lock:
        j = _jobs.get(name)
        return dict(j) if j else None


def schedule_proxy_work(
    root: Path,
    clip_path: Path,
    *,
    ensure_proxy,
    ensure_thumbnail,
    proxy_is_fresh,
    thumbnail_is_fresh,
    proxy_path_for_clip,
    thumbnail_path_for_clip,
) -> None:
    """Run ensure_proxy + ensure_thumbnail in a daemon thread."""
    name = clip_path.name

    def run() -> None:
        try:
            proxy = proxy_path_for_clip(root, clip_path)
            thumb = thumbnail_path_for_clip(root, clip_path)
            if not (proxy_is_fresh(clip_path, proxy) and thumbnail_is_fresh(clip_path, thumb)):
                ensure_proxy(root, clip_path, force=False)
                ensure_thumbnail(root, clip_path, force=False)
            clear_job(name)
        except Exception as e:  # noqa: BLE001
            mark_failed(name, str(e) or type(e).__name__)

    mark_processing(name)
    t = threading.Thread(target=run, name=f"footage-{name}", daemon=True)
    t.start()
