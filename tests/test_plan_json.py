"""Planner JSON extraction. Never calls the paid API."""

from __future__ import annotations

import json

import pytest

from plan import (
    build_json_retry_user_prompt,
    generate_plan,
    parse_plan_json,
    response_text_and_stop,
)


class _Block:
    def __init__(self, kind: str, text: str) -> None:
        self.type = kind
        self.text = text


class _Response:
    def __init__(self, blocks: list[_Block], stop_reason: str) -> None:
        self.content = blocks
        self.stop_reason = stop_reason


def test_text_blocks_are_concatenated_and_thinking_is_ignored():
    response = _Response(
        [
            _Block("thinking", "secret reasoning"),
            _Block("text", '{"schema_version": 2,'),
            _Block("text", ' "tracks": []}'),
        ],
        "end_turn",
    )
    text, stop = response_text_and_stop(response)
    assert "secret" not in text
    assert stop == "end_turn"
    data = parse_plan_json(text)
    assert data["schema_version"] == 2
    assert data["tracks"] == []


def test_parse_strips_fences_and_prose_and_keeps_braces_inside_strings():
    raw = (
        "Here is the timeline.\n"
        "```json\n"
        '{"schema_version": 2, "name": "a { b }", "tracks": []}\n'
        "```\n"
        "Let me know if you want changes."
    )
    data = parse_plan_json(raw)
    assert data["name"] == "a { b }"
    assert data["tracks"] == []


def test_truncated_object_is_not_a_column_1_error():
    with pytest.raises(ValueError, match="cut off") as exc:
        parse_plan_json('{"schema_version": 2, "tracks": [')
    assert "Expecting value" not in str(exc.value)


def test_retry_prompt_does_not_include_the_catalog():
    prompt = build_json_retry_user_prompt("not json", "max_tokens")
    assert "Media catalog" not in prompt
    assert "max_tokens" in prompt
    assert "not json" in prompt


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


def test_generate_plan_retries_once_without_catalog(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls: list[object] = []
    valid = {
        "schema_version": 2,
        "tracks": [{"id": "v1", "type": "video", "clips": []}],
    }

    def fake_call(model, system, user, api_key=None):
        calls.append(user)
        if len(calls) == 1:
            return ("I will plan this now.", None, "max_tokens")
        return (json.dumps(valid), None, "end_turn")

    monkeypatch.setattr("plan.call_claude", fake_call)
    monkeypatch.setattr(
        "plan.build_media_catalog",
        lambda *args, **kwargs: (
            [{"id": "clip.mp4", "analysis": {"merged_index": "complete"}}],
            [],
        ),
    )
    monkeypatch.setattr("plan.validate_plan_parsed", lambda *args, **kwargs: [])
    monkeypatch.setattr("plan.finalize_v2_direct", lambda plan, brief, gid: plan)

    plan, _group, _usage = generate_plan("12 second reel")
    assert plan["schema_version"] == 2
    assert len(calls) == 2
    first = _user_text(calls[0])
    second = _user_text(calls[1])
    assert "Media catalog" in first
    assert "clip.mp4" in first
    assert "Media catalog" not in second
    assert "clip.mp4" not in second
    saved = list((tmp_path / "plans" / "_planner_debug").glob("*.txt"))
    assert len(saved) == 1
    assert "stop_reason: max_tokens" in saved[0].read_text(encoding="utf-8")


def test_failed_retry_reports_max_tokens_and_saved_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_call(model, system, user, api_key=None):
        return ("", None, "max_tokens")

    monkeypatch.setattr("plan.call_claude", fake_call)
    monkeypatch.setattr(
        "plan.build_media_catalog",
        lambda *args, **kwargs: (
            [{"id": "clip.mp4", "analysis": {"merged_index": "complete"}}],
            [],
        ),
    )

    with pytest.raises(ValueError, match="max_tokens") as exc:
        generate_plan("12 second reel")
    message = str(exc.value)
    assert "Expecting value" not in message
    assert "Raw response saved" in message
    assert list((tmp_path / "plans" / "_planner_debug").glob("*.txt"))
