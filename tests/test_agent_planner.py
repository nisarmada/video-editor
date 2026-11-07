"""Agentic speech planner tools and self-correction loop (mocked API)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_planner import (  # noqa: E402
    AgentSession,
    audit_edl_cuts,
    dispatch_tool,
    generate_speech_edl,
    list_and_inspect_media,
    nudge_or_replace_cut,
    run_scripted_agent,
)
from plan import resolve_planner_clip_scope  # noqa: E402
from planner_speech_qa import audit_speech_edl_false_starts  # noqa: E402
from speech_layout import validate_timeline_speech_layout  # noqa: E402


@pytest.fixture
def agent_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "footage").mkdir()
    (tmp_path / "index").mkdir()
    (tmp_path / "plans").mkdir()
    (tmp_path / "index" / "app_settings.json").write_text(
        json.dumps({"audio_cut_refine": {"enabled": False}}),
        encoding="utf-8",
    )
    from index_cache import save_json, transcript_path  # noqa: E402

    clip = tmp_path / "footage" / "voice.m4a"
    clip.write_bytes(b"\x00")
    save_json(
        transcript_path(clip),
        {
            "clip": "voice.m4a",
            "language": "en",
            "segments": [
                {
                    "start": 0.0,
                    "end": 4.0,
                    "text": "Hello world today.",
                    "words": [
                        {"word": "Hello", "start": 0.2, "end": 0.6},
                        {"word": "world", "start": 0.7, "end": 1.1},
                        {"word": "today.", "start": 1.2, "end": 1.8},
                    ],
                }
            ],
        },
    )
    return tmp_path


def _edl_with_bad_decay() -> list[dict]:
    return [
        {
            "id": "s1",
            "source": "footage/voice.m4a",
            "source_in": 0.2,
            "source_out": 1.5,
            "speech_cut_quality": {
                "decay_retained_ms": 12,
                "click_score": 0.01,
                "energy_at_cut_db_below_peak": -30,
            },
            "cut_intent": {"start": "complete", "end": "complete"},
            "gap_after": {"mode": "continuous"},
        },
        {
            "id": "s2",
            "source": "footage/voice.m4a",
            "source_in": 2.0,
            "source_out": 3.5,
            "speech_cut_quality": {
                "decay_retained_ms": 80,
                "click_score": 0.01,
            },
            "cut_intent": {"start": "complete", "end": "complete"},
        },
    ]


def test_scripted_agent_detects_audit_failure_and_corrects(
    agent_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "agent_planner.validate_plan_data",
        lambda tl, target: ([], []),
    )
    steps = [
        {"tool": "list_and_inspect_media", "progress": "Scanning transcripts"},
        {
            "tool": "generate_speech_edl",
            "args": {"edl_items": _edl_with_bad_decay(), "brief": "short voice"},
        },
        {"tool": "audit_edl_cuts", "args": {}},
    ]
    session = AgentSession(agent_root)
    for step in steps:
        dispatch_tool(session, step["tool"], step.get("args") or {})
    assert session.last_audit is not None
    assert session.last_audit["pass"] is False
    assert session.last_audit["decay_issues"]

    nudge_or_replace_cut(
        session,
        timeline_json=session.timeline or {},
        clip_id="s1",
        action="extend_tail_ms",
        ms=80,
    )
    report = audit_edl_cuts(session, timeline_json=session.timeline)
    assert report["pass"] is True

    plan, group_id, usage = run_scripted_agent(
        "short voice",
        save_as="agent_test",
        root=agent_root,
        steps=[
            *steps,
            {
                "tool": "nudge_or_replace_cut",
                "args": {
                    "timeline_json": session.timeline,
                    "clip_id": "s1",
                    "action": "extend_tail_ms",
                    "ms": 80,
                },
            },
            {"tool": "audit_edl_cuts", "args": {}},
        ],
    )
    assert group_id
    assert usage["mode"] == "agentic"
    assert not validate_timeline_speech_layout(plan)
    words = {
        "footage/voice.m4a": [
            {"word": "Let", "start": 1.0, "end": 1.2},
            {"word": "me", "start": 1.2, "end": 1.4},
            {"word": "rephrase", "start": 1.4, "end": 2.0},
        ]
    }
    assert audit_speech_edl_false_starts(plan, words) == []


class _ToolUse:
    def __init__(self, id_: str, name: str, input_: dict) -> None:
        self.type = "tool_use"
        self.id = id_
        self.name = name
        self.input = input_


class _Text:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _MockResponse:
    def __init__(self, stop_reason: str, content: list, usage=None) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = usage


class MockAnthropicClient:
    """Returns tool_use then end_turn on second call."""

    def __init__(self, tool_plan: list[list[_ToolUse]]) -> None:
        self._turns = list(tool_plan)
        self.messages = self

    def create(self, **kwargs) -> _MockResponse:
        if not self._turns:
            return _MockResponse("end_turn", [_Text("done")])
        blocks = self._turns.pop(0)
        if blocks:
            return _MockResponse("tool_use", blocks)
        return _MockResponse("end_turn", [_Text("done")])


def test_mock_claude_issues_nudge_after_audit(agent_root: Path, monkeypatch):
    from agent_planner import dispatch_tool as real_dispatch  # noqa: E402
    from agent_planner import run_agentic_plan  # noqa: E402

    monkeypatch.setattr(
        "agent_planner.validate_plan_data",
        lambda tl, target: ([], []),
    )

    edl_args = {
        "edl_items": _edl_with_bad_decay(),
        "brief": "voice test",
    }
    client = MockAnthropicClient(
        [
            [
                _ToolUse("t1", "list_and_inspect_media", {}),
                _ToolUse("t2", "generate_speech_edl", edl_args),
                _ToolUse("t3", "audit_edl_cuts", {"timeline_json": {}}),
            ],
            [
                _ToolUse(
                    "t4",
                    "nudge_or_replace_cut",
                    {
                        "timeline_json": {},
                        "clip_id": "s1",
                        "action": "extend_tail_ms",
                        "ms": 80,
                    },
                ),
            ],
            [],
        ]
    )

    def wrapped_dispatch(session, name, arguments):
        if name == "audit_edl_cuts" and session.timeline is None:
            generate_speech_edl(session, **edl_args)
        if name == "nudge_or_replace_cut" and session.timeline:
            arguments = {**arguments, "timeline_json": session.timeline}
        if name == "audit_edl_cuts" and session.timeline and not arguments.get(
            "timeline_json"
        ):
            arguments = {**arguments, "timeline_json": session.timeline}
        return real_dispatch(session, name, arguments)

    monkeypatch.setattr("agent_planner.dispatch_tool", wrapped_dispatch)

    monkeypatch.setattr(
        "validate_plan.validate_plan_data",
        lambda tl, target: ([], []),
    )
    plan, gid, usage = run_agentic_plan(
        "voice test",
        save_as="mock_agent",
        root=agent_root,
        client=client,
        max_correction_loops=2,
    )
    assert gid
    assert usage["tool_calls"] >= 3
    assert not validate_timeline_speech_layout(plan)


def test_resolve_planner_clip_scope_primary_wins():
    assert resolve_planner_clip_scope(["a.mov", "b.m4a"], "voice.m4a") == ["voice.m4a"]


def test_single_source_rejects_other_files(agent_root: Path):
    session = AgentSession(agent_root)
    session.primary_source_file = "voice.m4a"
    ok = generate_speech_edl(
        session,
        edl_items=[
            {
                "id": "s1",
                "source": "footage/voice.m4a",
                "source_in": 0.0,
                "source_out": 1.0,
            },
        ],
    )
    assert "timeline" in ok
    bad = generate_speech_edl(
        session,
        edl_items=[
            {
                "id": "s2",
                "source": "footage/other.m4a",
                "source_in": 0.0,
                "source_out": 1.0,
            },
        ],
    )
    assert bad.get("error")
    insp = list_and_inspect_media(session, clip_filenames=None)
    assert insp.get("single_source_mode") is True
    assert len(insp.get("files") or []) <= 1
