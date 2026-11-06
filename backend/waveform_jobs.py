"""Background waveform peak generation for footage files (cached under index/)."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

_lock = threading.Lock()
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


def schedule_waveform_work(root: Path, clip_path: Path) -> None:
    """Compute peaks in a daemon thread; idempotent if job already running."""
    import sys
    from pathlib import Path as PathLib

    _scripts = PathLib(__file__).resolve().parents[1] / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))

    from index_cache import waveform_path
    from media import clip_metadata
    from waveform_peaks import compute_and_save_waveform

    name = clip_path.name
    ex = get_job(name)
    if ex and ex.get("status") == "processing":
        return

    src = clip_path if clip_path.is_absolute() else (root / clip_path).resolve()
    if not src.is_file():
        return

    try:
        _dur, has_audio, _r = clip_metadata(src)
    except (RuntimeError, OSError):
        return

    if not has_audio:
        return

    wpath = waveform_path(src)
    if wpath.is_file() and wpath.stat().st_mtime >= src.stat().st_mtime:
        return

    def run() -> None:
        try:
            compute_and_save_waveform(Path(root), src)
            clear_job(name)
        except Exception as e:  # noqa: BLE001
            mark_failed(name, str(e) or type(e).__name__)
            traceback.print_exc()

    mark_processing(name)
    t = threading.Thread(target=run, name=f"waveform-{name}", daemon=True)
    t.start()


def waveform_list_status(root: Path, clip_path: Path) -> str:
    """For GET /api/footage: none | pending | processing | ready | failed."""
    import sys
    from pathlib import Path as PathLib

    _scripts = PathLib(__file__).resolve().parents[1] / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))

    from index_cache import waveform_path
    from media import clip_metadata

    src = clip_path if clip_path.is_absolute() else (root / clip_path).resolve()
    if not src.is_file():
        return "none"

    try:
        _d, has_audio, _r = clip_metadata(src)
    except (RuntimeError, OSError):
        return "none"

    if not has_audio:
        return "none"

    job = get_job(src.name)
    if job:
        st = job.get("status")
        if st == "processing":
            return "processing"
        if st == "failed":
            return "failed"

    wp = waveform_path(src)
    if wp.is_file() and wp.stat().st_mtime >= src.stat().st_mtime:
        return "ready"
    return "pending"
