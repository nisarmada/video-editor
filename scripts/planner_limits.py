"""
Planner budgets, model tiers, and rough dollar estimates.

Token counts are len(text)/4. That is an estimate, not the API's tokenizer.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

# Edit model (Sonnet-class) and triage model (Haiku-class), $ per token.
EDIT_INPUT_USD = 3.0 / 1_000_000
EDIT_OUTPUT_USD = 15.0 / 1_000_000
TRIAGE_INPUT_USD = 1.0 / 1_000_000
TRIAGE_OUTPUT_USD = 5.0 / 1_000_000

# Guess for one timeline JSON reply when we have not called the model yet.
OUTPUT_TOKEN_GUESS = 1500

DEFAULTS: dict[str, Any] = {
    "catalog_token_budget": 8000,
    "confirm_above_usd": 0.10,
    "max_input_tokens": 24000,
    "max_cost_usd": 1.0,
    "max_iterations": 3,
    "max_images": 0,
    "max_wall_time_s": 180,
    "triage_model": "claude-haiku-4-5-20251001",
    "edit_model": "claude-sonnet-5-5",
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 3) // 4


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    *,
    tier: str = "edit",
) -> float:
    if tier == "triage":
        return input_tokens * TRIAGE_INPUT_USD + output_tokens * TRIAGE_OUTPUT_USD
    return input_tokens * EDIT_INPUT_USD + output_tokens * EDIT_OUTPUT_USD


def _as_int(value: Any, fallback: int, *, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(n, high))


def _as_float(value: Any, fallback: float, *, low: float, high: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(n, high))


def load_planner_settings(root: Path | None = None) -> dict[str, Any]:
    """
    Defaults, then index/app_settings.json "planner", then env model overrides.
    Env wins for the model names so a shell export still works.
    """
    out = dict(DEFAULTS)
    if root is not None:
        try:
            from backend.settings_store import load_raw

            raw = load_raw(root)
        except Exception:
            raw = {}
        stored = raw.get("planner") if isinstance(raw, dict) else None
        if isinstance(stored, dict):
            out.update({k: stored[k] for k in DEFAULTS if k in stored})
    out["catalog_token_budget"] = _as_int(
        out["catalog_token_budget"], DEFAULTS["catalog_token_budget"], low=500, high=200_000
    )
    out["confirm_above_usd"] = _as_float(
        out["confirm_above_usd"], DEFAULTS["confirm_above_usd"], low=0.0, high=100.0
    )
    out["max_input_tokens"] = _as_int(
        out["max_input_tokens"], DEFAULTS["max_input_tokens"], low=1000, high=2_000_000
    )
    out["max_cost_usd"] = _as_float(
        out["max_cost_usd"], DEFAULTS["max_cost_usd"], low=0.0, high=100.0
    )
    out["max_iterations"] = _as_int(
        out["max_iterations"], DEFAULTS["max_iterations"], low=1, high=20
    )
    out["max_images"] = _as_int(out["max_images"], DEFAULTS["max_images"], low=0, high=40)
    out["max_wall_time_s"] = _as_int(
        out["max_wall_time_s"], DEFAULTS["max_wall_time_s"], low=5, high=3600
    )
    triage_env = os.environ.get("ANTHROPIC_TRIAGE_MODEL", "").strip()
    edit_env = os.environ.get("ANTHROPIC_PLAN_MODEL", "").strip()
    if triage_env:
        out["triage_model"] = triage_env
    if edit_env:
        out["edit_model"] = edit_env
    if not str(out.get("triage_model") or "").strip():
        out["triage_model"] = DEFAULTS["triage_model"]
    if not str(out.get("edit_model") or "").strip():
        out["edit_model"] = DEFAULTS["edit_model"]
    return out


def public_planner_settings(root: Path) -> dict[str, Any]:
    """Settings the UI may show. No secrets."""
    return load_planner_settings(root)


class RunBudget:
    """Stops a run when tokens, dollars, iterations, images, or time run out."""

    def __init__(self, limits: dict[str, Any]) -> None:
        self.limits = limits
        self.started = time.perf_counter()
        self.iterations = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.images = 0
        self.stop_reason: str | None = None

    def elapsed_s(self) -> float:
        return time.perf_counter() - self.started

    def cost_usd(self) -> float:
        return estimate_cost_usd(self.input_tokens, self.output_tokens, tier="edit")

    def allow(self, *, est_input: int, est_output: int, images: int = 0) -> bool:
        """False means do not start another model call. stop_reason is set."""
        if self.iterations >= int(self.limits["max_iterations"]):
            self.stop_reason = "max_iterations"
            return False
        if self.elapsed_s() > float(self.limits["max_wall_time_s"]):
            self.stop_reason = "max_wall_time"
            return False
        if self.images + images > int(self.limits["max_images"]):
            self.stop_reason = "max_images"
            return False
        if self.input_tokens + est_input > int(self.limits["max_input_tokens"]):
            self.stop_reason = "max_input_tokens"
            return False
        next_cost = estimate_cost_usd(
            self.input_tokens + est_input,
            self.output_tokens + est_output,
            tier="edit",
        )
        if next_cost > float(self.limits["max_cost_usd"]):
            self.stop_reason = "max_cost"
            return False
        return True

    def note_call(self, input_tokens: int, output_tokens: int, images: int = 0) -> None:
        self.iterations += 1
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)
        self.images += images
