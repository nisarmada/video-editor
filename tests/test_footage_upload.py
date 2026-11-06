"""Footage upload and plan-reference checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app  # noqa: E402
from backend.paths import ProjectPaths, reset_paths, set_paths  # noqa: E402


@pytest.fixture
def client(tmp_path: Path):
    (tmp_path / "footage").mkdir()
    (tmp_path / "plans").mkdir()
    (tmp_path / "output").mkdir()
    set_paths(ProjectPaths(tmp_path))
    yield TestClient(app)
    reset_paths()


def test_upload_streams_and_validates(client: TestClient, tmp_path: Path, monkeypatch):
    vid = tmp_path / "small.mp4"
    vid.write_bytes(b"\x00" * 500)

    def fake_probe(path: Path) -> None:
        assert path.is_file()

    def noop_schedule(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("backend.main.ffprobe_validate_video", fake_probe)
    monkeypatch.setattr("backend.main.schedule_proxy_work", noop_schedule)
    monkeypatch.setattr(
        "backend.main.footage_entry",
        lambda root, clip_path: {
            "name": clip_path.name,
            "source": f"footage/{clip_path.name}",
            "duration_seconds": 1.0,
            "has_proxy": False,
            "has_thumbnail": False,
            "process_status": "processing",
            "process_error": None,
            "proxy_url": f"/api/footage/{clip_path.name}/proxy",
            "thumbnail_url": f"/api/footage/{clip_path.name}/thumbnail",
        },
    )

    with vid.open("rb") as f:
        r = client.post(
            "/api/footage/upload",
            files={"file": ("My Clip!.mp4", f, "video/mp4")},
        )
    assert r.status_code == 200
    data = r.json()
    assert "saved_as" in data
    saved = data["saved_as"]
    assert (tmp_path / "footage" / saved).is_file()


def test_delete_blocked_when_plan_references(client: TestClient, tmp_path: Path):
    (tmp_path / "footage" / "x.mp4").write_bytes(b"x")
    plan = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "v",
                "type": "video",
                "clips": [
                    {
                        "id": "c",
                        "source": "footage/x.mp4",
                        "source_in": 0,
                        "source_out": 1,
                        "timeline_start": 0,
                        "created_by": "user",
                    }
                ],
            }
        ],
    }
    (tmp_path / "plans" / "p.json").write_text(json.dumps(plan))

    r = client.delete("/api/footage/x.mp4")
    assert r.status_code == 409
    body = r.json()
    assert "p" in body["detail"]["plans"]
