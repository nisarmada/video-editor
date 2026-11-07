"""Background full index pipeline: transcript → silences → shots → keyframes → captions → merged index."""

from __future__ import annotations

import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from index_clip import build_merged_index  # noqa: E402

try:
    from backend.waveform_jobs import schedule_waveform_work  # noqa: E402
except ImportError:
    schedule_waveform_work = None  # type: ignore[misc, assignment]

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def mark_processing(name: str) -> None:
    with _lock:
        _jobs[name] = {"status": "processing", "error": None, "step": None}


def mark_failed(name: str, msg: str) -> None:
    with _lock:
        entry = _jobs.get(name, {})
        entry["status"] = "failed"
        entry["error"] = msg
        _jobs[name] = entry


def mark_step(name: str, step: str) -> None:
    with _lock:
        entry = _jobs.get(name, {})
        entry["step"] = step
        _jobs[name] = entry


def clear_job(name: str) -> None:
    with _lock:
        _jobs.pop(name, None)


def get_job(name: str) -> dict[str, Any] | None:
    with _lock:
        j = _jobs.get(name)
        return dict(j) if j else None


def schedule_index_pipeline(root: Path, clip_path: Path) -> None:
    """Run analysis scripts in order in a daemon thread."""
    name = clip_path.name
    existing = get_job(name)
    if existing and existing.get("status") == "processing":
        return

    src = clip_path if clip_path.is_absolute() else (root / clip_path).resolve()
    if not src.is_file():
        return

    repo = root.resolve()
    scripts_dir = repo / "scripts"
    py = sys.executable

    def run_script(rel_script: str, args: list[str], step: str) -> None:
        mark_step(name, step)
        cmd = [py, str(scripts_dir / rel_script), str(src), *args]
        r = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "script failed").strip()[-2000:]
            raise RuntimeError(f"{rel_script}: {err}")

    mark_processing(name)

    def run() -> None:
        try:
            # Order matches PROJECT.md pipeline (caption_frames needs keyframes)
            run_script("transcribe.py", [], "transcribe")
            run_script("silences.py", [], "silences")
            ext = src.suffix.lower()
            from footage_exts import AUDIO_EXTS, VIDEO_EXTS  # noqa: PLC0415

            if ext in AUDIO_EXTS:
                pass
            elif ext in VIDEO_EXTS:
                run_script("shots.py", [], "shots")
                run_script("keyframes.py", [], "keyframes")
                try:
                    run_script("caption_frames.py", [], "caption_frames")
                except RuntimeError:
                    mark_step(name, "caption_frames skipped (API or vision failed)")
            else:
                raise RuntimeError(f"Unsupported footage extension: {ext}")

            build_merged_index(src, force=True)

            if schedule_waveform_work is not None:
                try:
                    schedule_waveform_work(root, clip_path)
                except Exception:
                    pass

            clear_job(name)
        except Exception as e:  # noqa: BLE001
            mark_failed(name, str(e) or type(e).__name__)
            traceback.print_exc()

    t = threading.Thread(target=run, name=f"index-{name}", daemon=True)
    t.start()
