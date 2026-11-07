"""Background render jobs with cancel + progress callbacks."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Callable

ProgressFn = Callable[[float | None, str], None]

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _now_job(
    job_id: str,
    state: str,
    percent: float | None = None,
    error: str | None = None,
    log: str | None = None,
    output: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": job_id,
        "state": state,
        "percent": percent,
        "error": error,
        "log": log,
        "output": output,
        "url": url,
    }


def create_job() -> tuple[str, threading.Event]:
    job_id = str(uuid.uuid4())
    cancel = threading.Event()
    with _lock:
        _jobs[job_id] = {
            "state": "queued",
            "percent": None,
            "error": None,
            "log": "",
            "cancel": cancel,
            "output": None,
            "url": None,
        }
    return job_id, cancel


def update_job(
    job_id: str,
    *,
    state: str | None = None,
    percent: float | None = None,
    error: str | None = None,
    log_append: str | None = None,
    output: str | None = None,
    url: str | None = None,
    export_cut_quality: dict[str, Any] | None = None,
) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return
        if state is not None:
            j["state"] = state
        if percent is not None:
            j["percent"] = percent
        if error is not None:
            j["error"] = error
        if log_append:
            cur = j.get("log") or ""
            j["log"] = (cur + log_append)[-8000:]
        if output is not None:
            j["output"] = output
        if url is not None:
            j["url"] = url
        if export_cut_quality is not None:
            j["export_cut_quality"] = export_cut_quality


def get_job_public(job_id: str) -> dict[str, Any] | None:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return None
        out: dict[str, Any] = {
            "id": job_id,
            "state": j["state"],
            "percent": j.get("percent"),
            "error": j.get("error"),
            "log": j.get("log") or "",
            "output": j.get("output"),
            "url": j.get("url"),
        }
        if j.get("export_cut_quality") is not None:
            out["export_cut_quality"] = j["export_cut_quality"]
        return out


def request_cancel(job_id: str) -> bool:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return False
        ev = j.get("cancel")
        if isinstance(ev, threading.Event):
            ev.set()
        j["state"] = "cancelling"
        return True


def get_cancel_event(job_id: str) -> threading.Event | None:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return None
        ev = j.get("cancel")
        return ev if isinstance(ev, threading.Event) else None


def is_cancelled(job_id: str) -> bool:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return True
        ev = j.get("cancel")
        return isinstance(ev, threading.Event) and ev.is_set()


def bind_progress(job_id: str) -> ProgressFn:
    def _on(pct: float | None, msg: str = "") -> None:
        st = "running"
        with _lock:
            j = _jobs.get(job_id)
            if j and isinstance(j.get("cancel"), threading.Event) and j["cancel"].is_set():
                st = "cancelling"
        update_job(job_id, state=st, percent=pct, log_append=msg + "\n" if msg else None)

    return _on


def any_active_render() -> bool:
    with _lock:
        for j in _jobs.values():
            if j.get("state") in ("queued", "running", "cancelling"):
                return True
    return False
