"""One cheap-model read-back judge — brief + assembled speech only (no catalog)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from planner_limits import estimate_cost_usd, load_planner_settings

JUDGE_SYSTEM = """You are a human speech editor reviewing an assembled narration cut.
You only see the brief and the read-back script (clip order, declared cut_intent, text).
Return ONLY valid JSON (no markdown):
{
  "works_for_brief": boolean,
  "opening_hooks": boolean,
  "ending_lands": "resolve" | "trail_off" | "hangs" | "unclear",
  "summary": string,
  "issues": [
    {
      "clip_id": string,
      "severity": "info" | "warning" | "error",
      "message": string,
      "suggestion": { "source_in"?: number, "source_out"?: number, "unit_hint"?: string } | null
    }
  ]
}
"""


def parse_judge_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Judge response must be a JSON object")
    return data


def mock_judge_response(brief: str, readback: str) -> dict[str, Any]:
    """Deterministic stub for tests (no API)."""
    issues: list[dict[str, Any]] = []
    if "on the other hand" in readback.lower():
        issues.append(
            {
                "clip_id": "n1",
                "severity": "warning",
                "message": "Ending on connective 'on the other hand' reads accidental.",
                "suggestion": {"unit_hint": "end before connective"},
            }
        )
    if "fragment" in readback and "reason" not in readback:
        issues.append(
            {
                "clip_id": "n1",
                "severity": "warning",
                "message": "Fragment without stated reason.",
                "suggestion": None,
            }
        )
    hangs = "the" in readback.split()[-3:] and "complete" in readback
    return {
        "works_for_brief": len(issues) == 0,
        "opening_hooks": "remember" in readback.lower(),
        "ending_lands": "hangs" if hangs else "resolve",
        "summary": "Mock judge (no API spend).",
        "issues": issues,
        "mock": True,
        "est_cost_usd": 0.0,
    }


def call_readback_judge(
    *,
    brief: str,
    readback_text: str,
    root,
    api_key: str | None = None,
    mock: bool = False,
    caller: Callable[..., tuple[str, object]] | None = None,
) -> dict[str, Any]:
    if mock or os.environ.get("SPEECH_JUDGE_MOCK") == "1":
        out = mock_judge_response(brief, readback_text)
        out["readback_chars"] = len(readback_text)
        return out
    if not readback_text.strip():
        return {
            "works_for_brief": True,
            "opening_hooks": False,
            "ending_lands": "unclear",
            "summary": "No speech in timeline.",
            "issues": [],
            "est_cost_usd": 0.0,
        }

    limits = load_planner_settings(root)
    model = str(limits.get("triage_model") or "claude-haiku-4-5-20251001")
    user = (
        f"Brief:\n{brief}\n\n"
        "Read-back (timeline speech order):\n"
        f"{readback_text}\n\n"
        "Respond with JSON only."
    )
    est_in = max(200, len(user) // 4)
    est_out = 600
    est_cost = round(estimate_cost_usd(est_in, est_out, tier="triage"), 4)

    if caller is None:
        from plan import call_claude  # noqa: PLC0415

        text, usage, _stop = call_claude(
            model,
            JUDGE_SYSTEM,
            user,
            api_key=api_key,
        )
        in_tok = int(getattr(usage, "input_tokens", 0) or est_in)
        out_tok = int(getattr(usage, "output_tokens", 0) or est_out)
        est_cost = round(estimate_cost_usd(in_tok, out_tok, tier="triage"), 4)
    else:
        text, usage = caller(model, JUDGE_SYSTEM, user)
        in_tok = est_in
        out_tok = est_out

    parsed = parse_judge_json(text)
    parsed["model"] = model
    parsed["est_cost_usd"] = est_cost
    parsed["input_tokens"] = in_tok
    parsed["output_tokens"] = out_tok
    parsed["mock"] = False
    return parsed
