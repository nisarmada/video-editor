"""Project directory layout (footage/, plans/, index/proxies/, …)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_project_root() -> Path:
    env = os.environ.get("VIDEO_EDITOR_ROOT")
    if env:
        return Path(env).resolve()
    # backend/ -> repo root
    return Path(__file__).resolve().parents[1]


@dataclass
class ProjectPaths:
    root: Path

    @property
    def footage(self) -> Path:
        return self.root / "footage"

    @property
    def plans(self) -> Path:
        return self.root / "plans"

    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def index(self) -> Path:
        return self.root / "index"

    def plan_file(self, name: str) -> Path:
        stem = name if name.endswith(".json") else f"{name}.json"
        return self.plans / stem

    def output_file(self, name: str) -> Path:
        stem = name if name.endswith(".mp4") else f"{name}.mp4"
        return self.output / stem

    def safe_footage_name(self, name: str) -> Path:
        """Reject path traversal; return file under footage/."""
        base = Path(name).name
        path = self.footage / base
        if not path.is_file():
            raise FileNotFoundError(base)
        return path


_paths: ProjectPaths | None = None


def get_paths() -> ProjectPaths:
    global _paths
    if _paths is None:
        _paths = ProjectPaths(default_project_root())
    return _paths


def set_paths(paths: ProjectPaths) -> None:
    global _paths
    _paths = paths


def reset_paths() -> None:
    global _paths
    _paths = None
