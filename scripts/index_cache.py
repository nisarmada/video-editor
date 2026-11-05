"""Paths and simple file cache for index/ JSON artifacts."""

import json
from pathlib import Path


def index_dir() -> Path:
    path = Path.cwd() / "index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_path(video: Path) -> Path:
    return index_dir() / f"{video.stem}_transcript.json"


def silences_path(video: Path) -> Path:
    return index_dir() / f"{video.stem}_silences.json"


def load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def cache_hit(path: Path, force: bool) -> bool:
    return path.is_file() and not force
