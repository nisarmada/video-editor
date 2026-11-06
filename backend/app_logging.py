"""In-memory ring buffer for API / server events (no secrets)."""

from __future__ import annotations

import threading
import time
from collections import deque

_MAX = 500
_buffer: deque[dict] = deque(maxlen=_MAX)
_lock = threading.Lock()


def log_event(level: str, message: str, source: str = "server") -> None:
    """Append one line; never pass API keys or tokens."""
    entry = {
        "ts": time.time(),
        "level": level,
        "source": source,
        "message": message[:2000],
    }
    with _lock:
        _buffer.append(entry)


def get_logs(since: int = 0, limit: int = 200) -> list[dict]:
    """Return entries with index > since (monotonic index)."""
    with _lock:
        items = list(_buffer)
    out: list[dict] = []
    for i, e in enumerate(items):
        idx = i + 1
        if idx <= since:
            continue
        row = dict(e)
        row["id"] = idx
        out.append(row)
        if len(out) >= limit:
            break
    return out


def last_index() -> int:
    with _lock:
        return len(_buffer)


def all_entries_slice() -> list[dict]:
    with _lock:
        return list(_buffer)
