"""Index pipeline flags: free-only must not invoke caption_frames."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.index_jobs import schedule_index_pipeline  # noqa: E402


@pytest.fixture
def video_clip(tmp_path: Path) -> Path:
    footage = tmp_path / "footage"
    footage.mkdir()
    clip = footage / "clip.mp4"
    clip.write_bytes(b"fake")
    return clip


def test_free_only_skips_caption_frames(video_clip: Path, monkeypatch):
    scripts: list[str] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        scripts.append(Path(cmd[1]).name)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("backend.index_jobs.subprocess.run", fake_run)
    monkeypatch.setattr(
        "backend.index_jobs.build_merged_index",
        lambda *a, **k: {},
    )
    monkeypatch.setattr("backend.index_jobs.schedule_waveform_work", lambda *a, **k: None)

    def wait_done():
        import time
        from backend.index_jobs import get_job

        for _ in range(200):
            if get_job("clip.mp4") is None:
                return
            time.sleep(0.02)
        raise AssertionError("pipeline did not finish")

    schedule_index_pipeline(
        video_clip.parent.parent,
        video_clip,
        include_frame_captions=False,
    )
    wait_done()
    assert "caption_frames.py" not in scripts
    assert "transcribe.py" in scripts
    assert "keyframes.py" in scripts


def test_full_pipeline_includes_caption_frames(video_clip: Path, monkeypatch):
    scripts: list[str] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        scripts.append(Path(cmd[1]).name)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("backend.index_jobs.subprocess.run", fake_run)
    monkeypatch.setattr(
        "backend.index_jobs.build_merged_index",
        lambda *a, **k: {},
    )
    monkeypatch.setattr("backend.index_jobs.schedule_waveform_work", lambda *a, **k: None)

    import time
    from backend.index_jobs import get_job

    schedule_index_pipeline(
        video_clip.parent.parent,
        video_clip,
        include_frame_captions=True,
    )
    for _ in range(200):
        if get_job("clip.mp4") is None:
            break
        time.sleep(0.02)
    assert "caption_frames.py" in scripts


@pytest.fixture
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from backend.main import app  # noqa: PLC0415
    from backend.paths import ProjectPaths, reset_paths, set_paths  # noqa: PLC0415

    (tmp_path / "footage").mkdir()
    (tmp_path / "plans").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "footage" / "clip.mp4").write_bytes(b"fake")
    set_paths(ProjectPaths(tmp_path))
    yield TestClient(app)
    reset_paths()


def test_analyze_api_free_only_flag(client, monkeypatch):  # noqa: ANN001
    calls: list[bool] = []

    def capture(root, clip, **kwargs):  # noqa: ANN001
        calls.append(kwargs.get("include_frame_captions", True))

    monkeypatch.setattr("backend.main.schedule_index_pipeline", capture)
    r = client.post(
        "/api/footage/analyze",
        json={"names": ["clip.mp4"], "include_frame_captions": False},
    )
    assert r.status_code == 200
    assert calls == [False]
