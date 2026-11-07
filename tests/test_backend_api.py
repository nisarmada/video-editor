"""FastAPI backend (mock heavy pipeline steps)."""

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
    (tmp_path / "footage" / "clip.mp4").write_bytes(b"fake")
    set_paths(ProjectPaths(tmp_path))
    yield TestClient(app)
    reset_paths()


def _minimal_v2() -> dict:
    return {
        "schema_version": 2,
        "name": "test",
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "clips": [
                    {
                        "id": "c1",
                        "source": "footage/clip.mp4",
                        "source_in": 0.0,
                        "source_out": 1.0,
                        "timeline_start": 0.0,
                        "created_by": "user",
                    }
                ],
            },
            {"id": "track-audio-main", "type": "audio", "clips": []},
            {"id": "track-caption-main", "type": "caption", "clips": []},
        ],
    }


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_footage(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "proxy_media.video_duration_seconds",
        lambda p: 10.0,
    )
    r = client.get("/api/footage")
    assert r.status_code == 200
    data = r.json()
    assert len(data["clips"]) == 1
    assert data["clips"][0]["name"] == "clip.mp4"
    assert data["clips"][0]["process_status"] in ("pending", "ready")
    assert "waveform_status" in data["clips"][0]


def test_apply_timeline_op(client: TestClient):
    tl = _minimal_v2()
    r = client.post(
        "/api/timeline/apply-op",
        json={
            "timeline": tl,
            "operation": "set_clip_property",
            "arguments": {
                "clip_id": "c1",
                "properties": {"zoom": 1.2},
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["timeline"]["tracks"][0]["clips"][0]["zoom"] == 1.2
    assert body["undo"]["op"] == "set_clip_property"


def test_replace_timeline_undo(client: TestClient):
    tl = _minimal_v2()
    tl2 = _minimal_v2()
    tl2["name"] = "replaced"
    r = client.post(
        "/api/timeline/apply-op",
        json={
            "timeline": tl,
            "operation": "replace_timeline",
            "arguments": {"timeline_data": tl2},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["timeline"].get("name") == "replaced"
    assert body["undo"]["op"] == "replace_timeline"

    back = client.post(
        "/api/timeline/apply-op",
        json={
            "timeline": body["timeline"],
            "operation": "apply_undo",
            "arguments": {"undo": body["undo"]},
        },
    )
    assert back.status_code == 200
    restored = back.json()["timeline"]
    assert restored.get("name") == "test"
    assert len(restored["tracks"][0]["clips"]) == 1


def test_apply_undo_restores_delete(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "backend.main.validate_plan_data",
        lambda data, ml, **kwargs: ([], []),
    )

    tl = _minimal_v2()
    del_r = client.post(
        "/api/timeline/apply-op",
        json={
            "timeline": tl,
            "operation": "delete_clip",
            "arguments": {"clip_id": "c1"},
        },
    )
    assert del_r.status_code == 200
    deleted = del_r.json()
    assert deleted["timeline"]["tracks"][0]["clips"] == []
    undo_payload = deleted["undo"]

    back = client.post(
        "/api/timeline/apply-op",
        json={
            "timeline": deleted["timeline"],
            "operation": "apply_undo",
            "arguments": {"undo": undo_payload},
        },
    )
    assert back.status_code == 200
    restored = back.json()["timeline"]
    assert len(restored["tracks"][0]["clips"]) == 1
    assert restored["tracks"][0]["clips"][0]["id"] == "c1"


def test_save_and_load_plan(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "backend.main.validate_plan_data",
        lambda data, ml, **kwargs: ([], []),
    )

    tl = _minimal_v2()
    save = client.put("/api/plans/myedit", json={"timeline": tl})
    assert save.status_code == 200

    load = client.get("/api/plans/myedit")
    assert load.status_code == 200
    assert load.json()["schema_version"] == 2


def test_serve_proxy_mock(client: TestClient, monkeypatch, tmp_path: Path):
    proxy_file = tmp_path / "index" / "proxies" / "clip_540p.mp4"
    proxy_file.parent.mkdir(parents=True)
    proxy_file.write_bytes(b"not-really-mp4")

    def fake_ensure(root, clip, **kwargs):
        return proxy_file

    monkeypatch.setattr("backend.main.ensure_proxy", fake_ensure)
    r = client.get("/api/footage/clip.mp4/proxy")
    assert r.status_code == 200


def test_planner_run_mock(client: TestClient, monkeypatch):
    tl = _minimal_v2()

    def fake_plan(brief: str, **kwargs):
        return tl, "group-1", {"input_tokens": 1, "output_tokens": 2}

    monkeypatch.setattr("backend.main.generate_plan", fake_plan)
    r = client.post(
        "/api/planner/run",
        json={"brief": "10s test", "save_as": "auto"},
    )
    assert r.status_code == 200
    assert r.json()["group_id"] == "group-1"
    assert r.json()["plan_name"] == "auto.json"


def test_planner_full_mode_is_refused(client: TestClient, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("full mode must not call generate_plan")

    monkeypatch.setattr("backend.main.generate_plan", boom)
    r = client.post(
        "/api/planner/run",
        json={"brief": "10s test", "save_as": "auto", "mode": "full"},
    )
    assert r.status_code == 400
    assert "single_shot" in r.text or "agentic" in r.text


def test_planner_agentic_mode(client: TestClient, monkeypatch):
    tl = _minimal_v2()

    def fake_agent(*_args, **_kwargs):
        return tl, "agent-group", {"mode": "agentic", "tool_calls": 4}

    monkeypatch.setattr("backend.main.run_agentic_plan", fake_agent)
    r = client.post(
        "/api/planner/run",
        json={"brief": "voice reel", "save_as": "agent_plan", "mode": "agentic"},
    )
    assert r.status_code == 200
    assert r.json()["group_id"] == "agent-group"


def test_planner_estimate_does_not_call_the_model(client: TestClient, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("estimate must not call generate_plan")

    monkeypatch.setattr("backend.main.generate_plan", boom)
    monkeypatch.setattr(
        "backend.main.prepare_planner_context",
        lambda *args, **kwargs: {
            "file_count": 6,
            "omitted": 0,
            "unanalyzed": ["raw.mov"],
            "input_tokens": 9000,
            "est_cost_usd": 0.04,
            "confirm": False,
            "model": "claude-sonnet-5-5",
            "catalog_build_ms": 12,
        },
    )
    r = client.post("/api/planner/estimate", json={"brief": "30s reel"})
    assert r.status_code == 200
    body = r.json()
    assert body["file_count"] == 6
    assert body["input_tokens"] == 9000
    assert body["est_cost_usd"] == 0.04
    assert body["unanalyzed"] == ["raw.mov"]


def test_catalog_detail_slices_words(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "backend.main.build_media_catalog",
        lambda *args, **kwargs: (
            [
                {
                    "id": "clip.mp4",
                    "transcript_words": [
                        {"start": 0.0, "end": 0.4, "text": "hi"},
                        {"start": 5.0, "end": 5.4, "text": "later"},
                    ],
                    "shots": [{"start": 0, "end": 1}],
                    "keyframes": [],
                    "ai_frame_captions": [],
                }
            ],
            [],
        ),
    )
    r = client.get(
        "/api/media/catalog/detail",
        params={"name": "clip.mp4", "start": 0, "end": 1},
    )
    assert r.status_code == 200
    assert [word["text"] for word in r.json()["transcript_words"]] == ["hi"]


def test_planner_settings_roundtrip(client: TestClient):
    r = client.put(
        "/api/settings",
        json={"planner": {"catalog_token_budget": 4000, "confirm_above_usd": 0.2}},
    )
    assert r.status_code == 200
    planner = r.json()["planner"]
    assert planner["catalog_token_budget"] == 4000
    assert planner["confirm_above_usd"] == 0.2


def test_planner_run_passes_style_ids(client: TestClient, monkeypatch, tmp_path: Path):
    tl = _minimal_v2()
    captured: dict = {}

    def fake_plan(brief: str, **kwargs):
        captured.update(kwargs)
        return tl, "g", {}

    monkeypatch.setattr("backend.main.generate_plan", fake_plan)
    r = client.post(
        "/api/planner/run",
        json={
            "brief": "10s",
            "save_as": "with_style",
            "imitate_style_id": "a",
        },
    )
    assert r.status_code == 200
    assert captured.get("imitate_style_id") == "a"


def test_list_styles_empty(client: TestClient):
    r = client.get("/api/styles")
    assert r.status_code == 200
    assert r.json() == {"styles": []}


def test_list_styles_one(client: TestClient, tmp_path: Path):
    styles = tmp_path / "plans" / "styles"
    styles.mkdir(parents=True)
    (styles / "demo.json").write_text(
        '{"schema_version": 1, "style_id": "demo", "style_name": "Demo Ref"}\n',
        encoding="utf-8",
    )
    r = client.get("/api/styles")
    assert r.status_code == 200
    data = r.json()["styles"]
    assert len(data) == 1
    assert data[0]["id"] == "demo"
    assert data[0]["name"] == "Demo Ref"


def test_render_mock(client: TestClient, monkeypatch):
    called = {}

    def fake_render(plan_path, output_path, **kwargs):
        called["plan"] = plan_path
        output_path.write_bytes(b"mp4")

    monkeypatch.setattr(
        "backend.main.validate_plan_data",
        lambda data, ml, **kwargs: ([], []),
    )
    tl = _minimal_v2()
    save = client.put("/api/plans/myedit", json={"timeline": tl})
    assert save.status_code == 200

    monkeypatch.setattr("backend.main.render_plan_file", fake_render)
    start = client.post(
        "/api/render",
        json={"plan_name": "myedit", "output": "out.mp4"},
    )
    assert start.status_code == 200
    job_id = start.json()["job_id"]
    assert job_id
    import time

    for _ in range(50):
        st = client.get(f"/api/render/{job_id}")
        assert st.status_code == 200
        body = st.json()
        if body.get("state") == "done":
            assert "output/out.mp4" in (body.get("output") or "")
            assert called.get("plan") is not None
            break
        if body.get("state") in ("failed", "cancelled"):
            raise AssertionError(body)
        time.sleep(0.05)
    else:
        raise AssertionError("render job did not finish")


def test_speech_cut_audit_lists_boundaries(client: TestClient):
    tl = _minimal_v2()
    tl["tracks"].append(
        {
            "id": "A1",
            "type": "audio",
            "clips": [
                {
                    "id": "n1",
                    "source": "footage/x.m4a",
                    "source_in": 0,
                    "source_out": 1,
                    "timeline_start": 0,
                    "created_by": "user",
                }
            ],
        }
    )
    r = client.post("/api/timeline/speech-cut-audit", json={"timeline": tl})
    assert r.status_code == 200
    data = r.json()
    assert len(data.get("boundaries") or []) >= 2
    edges = {b["edge"] for b in data["boundaries"] if b["clip_id"] == "n1"}
    assert edges == {"in", "out"}
