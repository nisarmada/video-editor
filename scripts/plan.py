#!/usr/bin/env python3
"""
Ask Claude to build a timeline plan from a unified media catalog and a creative brief.
Usage: python scripts/plan.py --brief "30s reel, hook in first 2 seconds" --out plans/draft1.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from convert_v1_to_v2 import convert as v1_to_v2  # noqa: E402
from style_profile import format_style_for_prompt, load_style_profile  # noqa: E402
from timeline_format import get_track, is_v2  # noqa: E402
from validate_plan import validate_plan_data, validate_segments  # noqa: E402

from backend.media_catalog import build_media_catalog  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-5-20250514"
# User-facing default name; override with ANTHROPIC_PLAN_MODEL (e.g. claude-sonnet-5-5)
DEFAULT_MODEL_ENV = "claude-sonnet-5-5"

# Rough Sonnet-class $/token for console estimate (update if pricing changes)
INPUT_USD_PER_TOKEN = 3.0 / 1_000_000
OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000

BASE_SYSTEM_PROMPT = """You help build a timeline for a local video editor. Output area is typically 1080x1920 at 30 fps unless settings say otherwise.

You receive a JSON **media catalog**: one object per file in footage/. Each entry includes kind (video or audio), duration, stream flags, analysis status, transcript segments (or a note), silences, and for video files shots / keyframes / optional AI frame captions. Entries marked "not analyzed" for some fields mean that data was not produced yet — still use what is available.

You cannot see pixels or waveforms directly; rely on the catalog text and numbers.

## Timeline capabilities (schema version 2)

The project uses **multi-track** timelines:

- Any number of tracks of type `video`, `audio`, and `caption`.
- Each **clip** uses:
  - `id` (string, unique)
  - `source` — exactly `footage/<filename>` from the catalog
  - `source_in`, `source_out` — trim range in the source file (seconds)
  - `timeline_start` — where the clip begins on the timeline (seconds)
  - `created_by` — use `"ai"`
  - Optional: `group_id` (string) to link related clips
  - Optional: `speed`, `volume`, `zoom` (video)
  - Optional on **video** clips: `audio_source` — `"embedded"` (default) or `"detached"`:
    - `embedded`: mix the clip's own audio in the usual way.
    - `detached`: mute embedded audio for that video segment (use when audio comes only from another track).
  - Optional: `caption` on video clips as a short editorial note (not necessarily burned-in text)

**Caption track** clips need `text` (on-screen string) plus timing fields like video/audio.

**Gaps**: Leave timeline holes by advancing `timeline_start` so clips do not always touch; the renderer fills gaps with black + silence where needed.

**Audio-only files** (kind `audio` in the catalog): place them on **audio** tracks with `source` / trims / `timeline_start` / optional `speed` / `volume`. They can run under different video than their file name suggests, or alone.

**Video without audio**: valid; use `audio_source: detached` or rely on separate audio-track clips under the same timeline region.

You decide which files to use, how to trim them, and how to layer them. Omit files that do not fit the brief.

## Output format

Return **only** valid JSON (no markdown fences) with:

- `schema_version`: 2
- `name`: short slug
- `brief`: repeat the user's brief
- `target_length_seconds`: number (total timeline length you intend)
- `settings`: include at least `"width": 1080, "height": 1920, "fps": 30` unless the brief implies otherwise
- `tracks`: array of tracks, each with `id`, `type` (`video` | `audio` | `caption`), `label` (optional), `muted` (optional, for audio/video tracks), `clips` array

Validation rules you must satisfy:
- At least one clip on a **video** track (required for export).
- Every clip: valid `source` from the catalog, `source_in` < `source_out`, minimum segment length ~0.3s, times within file duration.
- Use only `footage/<filename>` sources present in the catalog.

Do not output legacy `segments`-only plans unless you cannot represent the edit otherwise; prefer full `schema_version` 2."""

DEFAULT_SETTINGS = {"width": 1080, "height": 1920, "fps": 30}


def build_system_prompt(
    *,
    imitate_profile: dict | None,
) -> str:
    """Anthropic system string: base rules plus optional reference-style blocks."""
    parts: list[str] = [BASE_SYSTEM_PROMPT]
    if imitate_profile is not None:
        parts.append(format_style_for_prompt("IMITATE", imitate_profile))
        parts.append(
            "Style mode — IMITATE: The user chose a reference profile. "
            "When it fits the brief, reflect similar pacing and structure; still use only "
            "catalog sources and valid times. Do not treat any track type as mandatory beyond "
            "what the export requires (at least one video clip)."
        )
    return "\n\n".join(parts)


def parse_target_seconds(brief: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?", brief, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*second", brief, re.I)
    if m:
        return float(m.group(1))
    return None


def build_user_prompt(
    brief: str,
    catalog: list[dict],
    catalog_warnings: list[str],
) -> str:
    target = parse_target_seconds(brief)
    target_line = (
        f"Target length: about {target} seconds total (timeline end)."
        if target
        else "Infer a sensible target_length_seconds from the brief."
    )
    warn_block = (
        "\nCatalog warnings:\n"
        + "\n".join(f"- {w}" for w in catalog_warnings)
        + "\n"
        if catalog_warnings
        else ""
    )
    catalog_json = json.dumps(catalog, indent=2, ensure_ascii=False)
    return (
        f"User brief:\n{brief}\n\n{target_line}\n"
        f"{warn_block}\n"
        "Media catalog (JSON):\n"
        f"{catalog_json}\n\n"
        "Return the timeline JSON object only (schema_version 2, see system instructions)."
    )


def parse_plan_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Plan must be a JSON object")
    if isinstance(data.get("tracks"), list) and data.get("schema_version") != 2:
        data = dict(data)
        data["schema_version"] = 2
    if data.get("schema_version") == 2:
        return data
    if "segments" in data:
        return data
    raise ValueError("Plan must have schema_version 2 or a legacy 'segments' array")


def ensure_ai_v2_plan(plan: dict, brief: str, run_group_id: str) -> dict:
    """Normalize model v2 output: defaults, created_by, group_id."""
    out = json.loads(json.dumps(plan))  # deep copy via JSON
    out["schema_version"] = 2
    out.setdefault("brief", brief)
    out.setdefault("name", "ai_plan")
    out.setdefault("settings", dict(DEFAULT_SETTINGS))
    if isinstance(out["settings"], dict):
        for k, v in DEFAULT_SETTINGS.items():
            out["settings"].setdefault(k, v)

    tracks = out.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("v2 plan needs tracks array")

    for track in tracks:
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            clip.setdefault("created_by", "ai")
    return out


def finalize_v2_from_segments(v1_plan: dict, brief: str, run_group_id: str) -> dict:
    """Legacy path: v1 segments → validate → convert to v2."""
    v1_plan = dict(v1_plan)
    v1_plan.setdefault("brief", brief)
    target_hint = parse_target_seconds(brief)
    if target_hint is not None:
        v1_plan.setdefault("target_length_seconds", target_hint)

    target = v1_plan.get("target_length_seconds")
    target = float(target) if isinstance(target, (int, float)) else None

    errors = validate_segments(v1_plan.get("segments") or [], target)
    if errors:
        raise ValueError(errors)

    v2 = v1_to_v2(v1_plan, created_by="ai", group_id=run_group_id)
    v2_errors, _v2_warnings = validate_plan_data(v2, target)
    if v2_errors:
        raise ValueError(v2_errors)
    return v2


# Backward-compatible name (tests import finalize_v2_plan)
finalize_v2_plan = finalize_v2_from_segments


def finalize_v2_direct(plan: dict, brief: str, run_group_id: str) -> dict:
    """Validate Claude v2 output."""
    plan = ensure_ai_v2_plan(plan, brief, run_group_id)
    target = plan.get("target_length_seconds")
    target = float(target) if isinstance(target, (int, float)) else None
    errors, _warn = validate_plan_data(plan, target)
    if errors:
        raise ValueError(errors)
    return plan


def validate_plan_parsed(plan: dict, brief: str, target: float | None) -> list[str]:
    """Unified validation errors for fix-pass."""
    if is_v2(plan):
        errs, _ = validate_plan_data(plan, target)
        return errs
    return validate_segments(plan.get("segments") or [], target)


def call_claude(
    model: str,
    system: str,
    user: str,
    *,
    api_key: str | None = None,
) -> tuple[str, object]:
    import anthropic

    key = (api_key or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in response.content if b.type == "text"]
    return "\n".join(parts), response.usage


def print_usage(usage: object, model: str) -> None:
    if usage is None:
        return
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    est = inp * INPUT_USD_PER_TOKEN + out * OUTPUT_USD_PER_TOKEN
    print(f"Tokens ({model}): input={inp} output={out}  (~${est:.4f} estimated)")


def generate_plan(
    brief: str,
    *,
    api_key: str | None = None,
    clip_filenames: list[str] | None = None,
    imitate_style_id: str | None = None,
    require_merged_index: bool = True,
) -> tuple[dict, str, dict]:
    """
    Call Claude, validate, return v2 plan, group_id, and token usage tallies.
    Requires cwd = project root (footage/, index/).
    If clip_filenames is set, only those footage basenames are in the catalog.
    """
    load_dotenv()

    root = Path.cwd()
    imitate_profile: dict | None = None
    if imitate_style_id:
        imitate_profile = load_style_profile(root, imitate_style_id)

    system_prompt = build_system_prompt(imitate_profile=imitate_profile)

    scope = "selected" if clip_filenames else "all"
    catalog, cat_warnings = build_media_catalog(
        root,
        scope=scope,
        only_basenames=clip_filenames,
    )
    if not catalog:
        raise RuntimeError(
            "No media files in footage/. Add clips (video and/or audio), then run analysis."
        )

    if require_merged_index:
        missing_merged = [
            e["id"]
            for e in catalog
            if (e.get("analysis") or {}).get("merged_index") != "complete"
        ]
        if missing_merged:
            joined = ", ".join(missing_merged)
            raise RuntimeError(
                "Merged index missing for: "
                f"{joined}. Run POST /api/footage/analyze with these names, "
                "or wait for analysis to finish."
            )

    user_prompt = build_user_prompt(brief, catalog, cat_warnings)

    requested = os.environ.get("ANTHROPIC_PLAN_MODEL", DEFAULT_MODEL_ENV)
    model_candidates = [requested]
    if requested == DEFAULT_MODEL_ENV and DEFAULT_MODEL not in model_candidates:
        model_candidates.append(DEFAULT_MODEL)

    total_usage: dict = {"input_tokens": 0, "output_tokens": 0}
    text: str | None = None
    model_used = requested

    for i, current_model in enumerate(model_candidates):
        try:
            text, usage = call_claude(
                current_model, system_prompt, user_prompt, api_key=api_key
            )
            model_used = current_model
            break
        except Exception as e:
            if i < len(model_candidates) - 1:
                continue
            raise RuntimeError(f"Planner API error: {e}") from e

    assert text is not None
    if usage:
        total_usage["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
        total_usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0

    try:
        plan = parse_plan_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Invalid plan JSON from model: {e}") from e

    run_group_id = str(uuid.uuid4())
    target = parse_target_seconds(brief) or plan.get("target_length_seconds")
    target = float(target) if isinstance(target, (int, float)) else None

    errors = validate_plan_parsed(plan, brief, target)
    if errors:
        fix_prompt = (
            user_prompt
            + "\n\nYour previous JSON failed validation:\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\n\nReturn a corrected JSON object only."
        )
        try:
            text, usage2 = call_claude(
                model_used, system_prompt, fix_prompt, api_key=api_key
            )
        except Exception as e:
            raise RuntimeError(f"Planner API error on fix pass: {e}") from e
        if usage2:
            total_usage["input_tokens"] += getattr(usage2, "input_tokens", 0) or 0
            total_usage["output_tokens"] += getattr(usage2, "output_tokens", 0) or 0
        try:
            plan = parse_plan_json(text)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid fixed plan JSON: {e}") from e
        errors = validate_plan_parsed(plan, brief, target)
        if errors:
            raise ValueError(errors)

    if is_v2(plan):
        plan_v2 = finalize_v2_direct(plan, brief, run_group_id)
    else:
        plan_v2 = finalize_v2_from_segments(plan, brief, run_group_id)

    total_usage["model"] = model_used
    return plan_v2, run_group_id, total_usage


def print_summary(plan: dict) -> None:
    if is_v2(plan):
        video = get_track(plan, "video") or {}
        clips = sorted(
            video.get("clips") or [],
            key=lambda c: float(c["timeline_start"]),
        )
        total = sum(
            float(c["source_out"]) - float(c["source_in"]) for c in clips
        )
        print(f"\nPlan summary: {len(clips)} video clips, {total:.2f}s source span")
        for i, clip in enumerate(clips):
            reason = clip.get("caption") or "(no reason)"
            src = Path(clip.get("source", "?")).name
            start = clip.get("source_in")
            end = clip.get("source_out")
            print(f"  {i + 1}. {src} [{start}-{end}s] — {reason}")
        audio_tracks = [t for t in plan.get("tracks") or [] if t.get("type") == "audio"]
        ac = sum(len(t.get("clips") or []) for t in audio_tracks)
        if ac:
            print(f"  Audio clips (all audio tracks): {ac}")
        return

    segments = plan.get("segments") or []
    total = sum(
        float(s["end"]) - float(s["start"])
        for s in segments
        if "start" in s and "end" in s
    )
    print(f"\nPlan summary: {len(segments)} segments, {total:.2f}s total")
    for i, seg in enumerate(segments):
        reason = seg.get("reason") or seg.get("caption") or "(no reason)"
        src = Path(seg.get("source", "?")).name
        start = seg.get("start")
        end = seg.get("end")
        print(f"  {i + 1}. {src} [{start}-{end}s] — {reason}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Generate edit plan with Claude")
    parser.add_argument("--brief", required=True, help="Creative brief for the reel")
    parser.add_argument("--out", required=True, type=Path, help="Output plan JSON path")
    parser.add_argument(
        "--imitate-style",
        dest="imitate_style_id",
        default=None,
        help="Style profile id under plans/styles/<id>.json to mirror",
    )
    args = parser.parse_args()

    try:
        plan_v2, run_group_id, total_usage = generate_plan(
            args.brief,
            imitate_style_id=args.imitate_style_id,
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        errs = e.args[0] if e.args and isinstance(e.args[0], list) else [str(e)]
        print("Plan validation failed:", file=sys.stderr)
        for err in errs:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan_v2, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved v2 plan: {args.out}  (group_id={run_group_id})")

    if total_usage.get("input_tokens") or total_usage.get("output_tokens"):

        class U:
            pass

        u = U()
        u.input_tokens = total_usage.get("input_tokens", 0)
        u.output_tokens = total_usage.get("output_tokens", 0)
        print("\nTotal API usage this run:")
        print_usage(u, total_usage.get("model", DEFAULT_MODEL_ENV))

    print_summary(plan_v2)


if __name__ == "__main__":
    main()
