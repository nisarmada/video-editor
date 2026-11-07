"""Speech edit warnings and read-back judge (mocked — no paid API)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from speech_edit_quality import (  # noqa: E402
    assemble_readback,
    mechanical_speech_warnings,
    readback_script_text,
)
from speech_readback_judge import call_readback_judge, mock_judge_response  # noqa: E402
from speech_units import build_speech_units  # noqa: E402

PLAN1 = ROOT / "plans" / "plan-1.json"


def _tl_audio_only(words_text: str) -> dict:
    return {
        "schema_version": 2,
        "tracks": [
            {
                "id": "V",
                "type": "video",
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/x.mp4",
                        "source_in": 0,
                        "source_out": 5,
                        "timeline_start": 0,
                        "audio_source": "detached",
                    }
                ],
            },
            {
                "id": "A",
                "type": "audio",
                "clips": [
                    {
                        "id": "n1",
                        "source": "footage/narr.wav",
                        "source_in": 0.0,
                        "source_out": 3.0,
                        "timeline_start": 0.0,
                        "cut_intent": {
                            "start": "fragment",
                            "end": "complete",
                            "reason": "Ramble trimmed to hook",
                        },
                    }
                ],
            },
        ],
    }


@pytest.fixture
def narration_project(render_project_root: Path, monkeypatch):
    """Footage + transcript for speech unit tests."""
    from tests.conftest import _write_narration_index, _write_narration_m4a

    root = render_project_root
    _write_narration_m4a(root / "footage" / "narration.m4a")
    _write_narration_index(root, "narration")
    media = root / "footage" / "narration.m4a"
    doc = build_speech_units(media)
    from index_cache import save_json_atomic, speech_units_path

    save_json_atomic(speech_units_path(media), doc)
    return root


def test_fragment_with_reason_no_missing_intent_warning(narration_project: Path):
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A",
                "type": "audio",
                "clips": [
                    {
                        "id": "n1",
                        "source": "footage/narration.m4a",
                        "source_in": 0.5,
                        "source_out": 2.5,
                        "timeline_start": 0.0,
                        "cut_intent": {
                            "start": "fragment",
                            "end": "complete",
                            "reason": "Opens mid-thought on purpose",
                        },
                    }
                ],
            },
            {
                "id": "V",
                "type": "video",
                "clips": [
                    {
                        "id": "v1",
                        "source": "footage/clip.mp4",
                        "source_in": 0,
                        "source_out": 10,
                        "timeline_start": 0,
                        "audio_source": "detached",
                    }
                ],
            },
        ],
    }
    warns = mechanical_speech_warnings(tl, root=narration_project)
    codes = {w["code"] for w in warns}
    assert "fragment_without_reason" not in codes


def test_unexplained_fragment_warns(narration_project: Path):
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A",
                "type": "audio",
                "clips": [
                    {
                        "id": "n1",
                        "source": "footage/narration.m4a",
                        "source_in": 0.5,
                        "source_out": 2.5,
                        "timeline_start": 0.0,
                        "cut_intent": {"start": "fragment", "end": "complete"},
                    }
                ],
            }
        ],
    }
    warns = mechanical_speech_warnings(tl, root=narration_project)
    assert any(w["code"] == "fragment_without_reason" for w in warns)


def test_old_plan_without_cut_intent_does_not_crash(narration_project: Path):
    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A",
                "type": "audio",
                "clips": [
                    {
                        "id": "n1",
                        "source": "footage/narration.m4a",
                        "source_in": 0.5,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                    }
                ],
            }
        ],
    }
    warns = mechanical_speech_warnings(tl, root=narration_project)
    assert any(w["code"] == "missing_cut_intent" for w in warns)


def test_judge_mock_flags_connective():
    text = "[n1] (start=complete, end=complete): on the other hand we should"
    v = mock_judge_response("brief", text)
    assert v["mock"] is True
    assert any("other hand" in i.get("message", "") for i in v.get("issues", []))


def test_judge_no_catalog_in_call(monkeypatch):
    captured: dict = {}

    def fake_call(model, system, user, api_key=None):
        captured["system"] = system
        captured["user"] = user
        return "{}", None

    call_readback_judge(
        brief="b",
        readback_text="hello",
        root=Path.cwd(),
        mock=False,
        caller=lambda m, s, u: fake_call(m, s, u),
    )
    assert "catalog" not in captured.get("user", "").lower()


def test_no_speech_timeline_untouched():
    tl = {"schema_version": 2, "tracks": [{"id": "V", "type": "video", "clips": []}]}
    blocks = assemble_readback(tl, root=Path.cwd())
    assert blocks == []
    v = call_readback_judge(brief="x", readback_text="", root=Path.cwd(), mock=True)
    assert v.get("issues") == []


def test_plan1_mechanical_warnings_real_repo():
    if not PLAN1.is_file():
        pytest.skip("plan-1.json not present")
    plan = json.loads(PLAN1.read_text())
    warns = mechanical_speech_warnings(plan, root=ROOT)
    codes = {w["code"] for w in warns}
    assert "missing_cut_intent" in codes or "ends_on_function_word" in codes or "final_speech_hangs" in codes


def test_apply_suggestion_idempotent(narration_project: Path):
    from timeline_ops import apply_speech_suggestion

    tl = {
        "schema_version": 2,
        "tracks": [
            {
                "id": "A",
                "type": "audio",
                "clips": [
                    {
                        "id": "n1",
                        "source": "footage/narration.m4a",
                        "source_in": 1.0,
                        "source_out": 2.0,
                        "timeline_start": 0.0,
                    }
                ],
            }
        ],
    }
    once = apply_speech_suggestion(tl, clip_id="n1", source_out=1.8)
    twice = apply_speech_suggestion(once["timeline"], clip_id="n1", source_out=1.8)
    assert twice["timeline"]["tracks"][0]["clips"][0]["source_out"] == 1.8
