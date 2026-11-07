"""Cheap planner: budgets, compact catalog, repair scope, cached prefix. No paid API."""

from __future__ import annotations

import json

import pytest

from plan import generate_plan
from index_cache import save_json_atomic
from planner_catalog import (
    catalog_json,
    detail_slice,
    select_compact,
)
from planner_limits import estimate_tokens


def _user_text(user: object) -> str:
    if isinstance(user, str):
        return user
    if isinstance(user, list):
        parts: list[str] = []
        for block in user:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(user)


def _analyzed(file_id: str, text: str) -> dict:
    return {
        "id": file_id,
        "kind": "video",
        "duration_seconds": 10,
        "has_audio": True,
        "width": 1920,
        "height": 1080,
        "analysis": {"merged_index": "complete"},
        "transcript_segments": [{"text": text}],
    }


def test_budget_stop_keeps_the_draft(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "index").mkdir()
    (tmp_path / "index" / "app_settings.json").write_text(
        json.dumps({"planner": {"max_iterations": 1}}),
        encoding="utf-8",
    )
    calls: list[object] = []
    draft = {
        "schema_version": 2,
        "draft_marker": "kept",
        "tracks": [
            {
                "id": "v",
                "type": "video",
                "clips": [{"id": "c1", "source": "footage/keep.mp4"}],
            }
        ],
    }

    def fake_call(model, system, user, api_key=None):
        calls.append(user)
        return (json.dumps(draft), None, "end_turn")

    def fail_finalize(plan, brief, gid):
        raise AssertionError("finalize should not run when the budget stops")

    monkeypatch.setattr("plan.call_claude", fake_call)
    monkeypatch.setattr(
        "plan.build_media_catalog",
        lambda *args, **kwargs: ([_analyzed("keep.mp4", "keep this")], []),
    )
    monkeypatch.setattr(
        "plan.validate_plan_parsed",
        lambda *args, **kwargs: ["source footage/keep.mp4 is outside the file"],
    )
    monkeypatch.setattr("plan.finalize_v2_direct", fail_finalize)
    monkeypatch.setattr("plan.finalize_v2_from_segments", fail_finalize)

    plan, _group, usage = generate_plan("12 second reel")
    assert len(calls) == 1
    assert plan["draft_marker"] == "kept"
    assert plan["planner_run"]["budget_stop"] == "max_iterations"
    assert usage["budget_stop"] == "max_iterations"
    assert plan["planner_run"]["validation_errors"]


def test_repair_call_omits_unrelated_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls: list[object] = []
    draft = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "v",
                "type": "video",
                "clips": [
                    {
                        "id": "c1",
                        "source": "footage/keep.mp4",
                        "source_in": 0,
                        "source_out": 1,
                        "timeline_start": 0,
                    }
                ],
            }
        ],
    }
    checks = {"n": 0}

    def fake_call(model, system, user, api_key=None):
        calls.append(user)
        return (json.dumps(draft), None, "end_turn")

    def fake_validate(plan, brief, target):
        checks["n"] += 1
        if checks["n"] == 1:
            return ["source footage/keep.mp4 extends past the file"]
        return []

    monkeypatch.setattr("plan.call_claude", fake_call)
    monkeypatch.setattr(
        "plan.build_media_catalog",
        lambda *args, **kwargs: (
            [
                _analyzed("keep.mp4", "KEEP_FILE_TOKEN is the one to use."),
                _analyzed("other.mp4", "OTHER_FILE_TOKEN should stay out of the repair."),
                {
                    "id": "raw.mov",
                    "kind": "video",
                    "analysis": {"merged_index": "missing"},
                    "transcript_segments": [{"text": "SECRET_UNANALYZED_TRANSCRIPT"}],
                },
            ],
            [],
        ),
    )
    monkeypatch.setattr("plan.validate_plan_parsed", fake_validate)
    monkeypatch.setattr("plan.finalize_v2_direct", lambda plan, brief, gid: plan)

    generate_plan("12 second reel")
    assert len(calls) == 2
    first = _user_text(calls[0])
    repair = _user_text(calls[1])
    assert "keep.mp4" in first
    assert "other.mp4" in first
    assert "SECRET_UNANALYZED_TRANSCRIPT" not in first
    assert "raw.mov" in first
    assert "KEEP_FILE_TOKEN" in repair
    assert "keep.mp4" in repair
    assert "OTHER_FILE_TOKEN" not in repair
    assert "other.mp4" not in repair
    assert "SECRET_UNANALYZED_TRANSCRIPT" not in repair


def test_compact_catalog_respects_token_budget(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    writes = {"n": 0}
    real_save = save_json_atomic

    def counting(path, payload):
        writes["n"] += 1
        real_save(path, payload)

    monkeypatch.setattr("text_embeddings.save_json_atomic", counting)
    entries = []
    for i in range(200):
        entries.append(
            {
                "id": f"file_{i:03d}.mp4",
                "kind": "video",
                "duration_seconds": 12.5,
                "has_audio": True,
                "width": 1920,
                "height": 1080,
                "silence_ratio_estimate": 0.2,
                "shots": [{"start": 0, "end": 1}] * 3,
                "transcript_words": [{"text": "word"}] * 40,
                "analysis": {"merged_index": "complete"},
                "transcript_segments": [
                    {"text": f"Unique hook {i}. " + ("ocean reel sentence. " * 30)}
                ],
                "ai_frame_captions": [
                    {"description": f"Wide shot number {i} of the coast."}
                ],
            }
        )
    entries.append(
        {
            "id": "raw.mov",
            "kind": "video",
            "analysis": {"merged_index": "missing"},
            "transcript_segments": [{"text": "SECRET_UNANALYZED_TRANSCRIPT"}],
        }
    )
    brief = "30s reel, hook in first 2 seconds"
    rows, omitted, unanalyzed = select_compact(entries, brief, 8000)
    assert unanalyzed == ["raw.mov"]
    assert omitted > 0
    assert rows
    assert all(row["id"] != "raw.mov" for row in rows)
    assert estimate_tokens(catalog_json(rows)) <= 8000
    assert "SECRET_UNANALYZED_TRANSCRIPT" not in catalog_json(rows)
    first_writes = writes["n"]
    assert first_writes > 0
    rows_again, omitted_again, _ = select_compact(entries, brief, 8000)
    assert [row["id"] for row in rows_again] == [row["id"] for row in rows]
    assert omitted_again == omitted
    assert writes["n"] == first_writes


def test_repeated_static_prefix_is_marked_for_cache(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seen: list[tuple[object, object]] = []

    def fake_call(model, system, user, api_key=None):
        seen.append((system, user))
        body = {"schema_version": 2, "tracks": [{"id": "v", "type": "video", "clips": []}]}
        return (json.dumps(body), None, "end_turn")

    monkeypatch.setattr("plan.call_claude", fake_call)
    monkeypatch.setattr(
        "plan.build_media_catalog",
        lambda *args, **kwargs: ([_analyzed("clip.mp4", "a short line")], []),
    )
    monkeypatch.setattr("plan.validate_plan_parsed", lambda *args, **kwargs: [])
    monkeypatch.setattr("plan.finalize_v2_direct", lambda plan, brief, gid: plan)

    generate_plan("alpha cut")
    generate_plan("beta cut")
    assert len(seen) == 2
    system_a, user_a = seen[0]
    system_b, user_b = seen[1]
    assert system_a == system_b
    assert isinstance(system_a, list)
    assert system_a[0]["cache_control"] == {"type": "ephemeral"}
    assert system_a[1]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(user_a, list) and isinstance(user_b, list)
    assert user_a[0] == user_b[0]
    assert user_a[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in user_a[1]
    assert user_a[1]["text"] != user_b[1]["text"]


def test_detail_slice_keeps_words_in_range():
    entry = {
        "id": "clip.mp4",
        "transcript_words": [
            {"start": 0.0, "end": 0.4, "text": "hi"},
            {"start": 5.0, "end": 5.4, "text": "later"},
        ],
        "shots": [{"start": 0, "end": 1}],
        "keyframes": [{"time": 0.2}],
        "ai_frame_captions": [{"description": "a face"}],
    }
    detail = detail_slice(entry, start=0, end=1)
    assert [word["text"] for word in detail["transcript_words"]] == ["hi"]
    assert detail["shots"] == [{"start": 0, "end": 1}]
    assert detail["keyframes"] == [{"time": 0.2}]
    assert detail["ai_frame_captions"][0]["description"] == "a face"


def test_full_mode_does_not_call_the_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_call(*args, **kwargs):
        raise AssertionError("full mode must not call the model")

    monkeypatch.setattr("plan.call_claude", fake_call)
    with pytest.raises(RuntimeError, match="Use Draft"):
        generate_plan("12 second reel", mode="full")
