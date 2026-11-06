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


def _safe_subdir(root: Path, rel: str, default: str) -> str:
    """One path segment under root, no traversal."""
    raw = (rel or default).strip() or default
    seg = Path(raw).parts[0] if Path(raw).parts else default
    if not seg or seg in (".", "..") or "/" in seg or "\\" in seg:
        return default
    return seg


@dataclass
class ProjectPaths:
    root: Path
    footage_rel: str = "footage"
    plans_rel: str = "plans"
    output_rel: str = "output"

    @property
    def footage(self) -> Path:
        p = (self.root / self.footage_rel).resolve()
        self._assert_under_root(p)
        return p

    @property
    def plans(self) -> Path:
        p = (self.root / self.plans_rel).resolve()
        self._assert_under_root(p)
        return p

    @property
    def output(self) -> Path:
        p = (self.root / self.output_rel).resolve()
        self._assert_under_root(p)
        return p

    @property
    def index(self) -> Path:
        return self.root / "index"

    def _assert_under_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root.resolve())
        except ValueError as e:
            raise ValueError(f"Path must stay under project root: {path}") from e

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


def refresh_paths_from_settings() -> ProjectPaths:
    """Apply index/app_settings.json path overrides (single segment each)."""
    global _paths
    root = default_project_root() if _paths is None else _paths.root
    from backend.settings_store import load_raw  # noqa: WPS433

    raw = load_raw(root)
    paths_cfg = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
    footage = _safe_subdir(root, str(paths_cfg.get("footage", "footage")), "footage")
    plans = _safe_subdir(root, str(paths_cfg.get("plans", "plans")), "plans")
    output = _safe_subdir(root, str(paths_cfg.get("output", "output")), "output")
    _paths = ProjectPaths(root=root, footage_rel=footage, plans_rel=plans, output_rel=output)
    return _paths


def get_paths() -> ProjectPaths:
    return refresh_paths_from_settings()


def set_paths(paths: ProjectPaths) -> None:
    global _paths
    _paths = paths


def reset_paths() -> None:
    global _paths
    _paths = None
