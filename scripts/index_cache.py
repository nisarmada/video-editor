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


def shots_path(video: Path) -> Path:
    return index_dir() / f"{video.stem}_shots.json"


def keyframes_path(video: Path) -> Path:
    return index_dir() / f"{video.stem}_keyframes.json"


def captions_path(video: Path) -> Path:
    return index_dir() / f"{video.stem}_captions.json"


def merged_index_path(video: Path) -> Path:
    return index_dir() / f"{video.stem}.json"


def waveform_path(video: Path) -> Path:
    """Cached peak envelope JSON for timeline waveforms (next to other index artifacts)."""
    return index_dir() / f"{video.stem}_waveform.json"


def keyframes_dir(video: Path) -> Path:
    return index_dir() / "keyframes" / video.stem


def load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def save_json_atomic(path: Path, payload: dict | list) -> None:
    """Write JSON via a temp file then replace, so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def cache_hit(path: Path, force: bool) -> bool:
    return path.is_file() and not force
