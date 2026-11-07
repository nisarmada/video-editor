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
import time
import uuid
from datetime import datetime, timezone
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
from audio_cut_refine import load_settings, refine_timeline_audio_cuts  # noqa: E402
from speech_layout import build_speech_layout, detect_and_normalize_edl  # noqa: E402
from validate_plan import validate_plan_data, validate_segments  # noqa: E402

from backend.media_catalog import build_media_catalog  # noqa: E402
from index_cache import load_json, planner_usage_path, save_json_atomic  # noqa: E402
from planner_catalog import (  # noqa: E402
    build_repair_prompt,
    cached_system_blocks,
    catalog_block,
    content_as_text,
    select_compact,
    user_content_blocks,
)
from planner_limits import (  # noqa: E402
    OUTPUT_TOKEN_GUESS,
    RunBudget,
    estimate_cost_usd,
    estimate_tokens,
    load_planner_settings,
)

DEFAULT_MODEL = "claude-sonnet-4-5-20250514"
# User-facing default name; override with ANTHROPIC_PLAN_MODEL (e.g. claude-sonnet-5-5)
DEFAULT_MODEL_ENV = "claude-sonnet-5-5"

# Rough Sonnet-class $/token for console estimate (update if pricing changes)
INPUT_USD_PER_TOKEN = 3.0 / 1_000_000
OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000
PLANNER_MAX_TOKENS = 8192

BASE_SYSTEM_PROMPT = """You help build a timeline for a local video editor. Output area is typically 1080x1920 at 30 fps unless settings say otherwise.

You receive a **compact media catalog**: one small object per analyzed file (id, kind, duration, a one-line summary, a few measurements, analysis status, and a short transcript_digest). Files that are not analyzed are listed by name only and must not be used. Full word lists, shots, and frames are not in this request.

You cannot see pixels or waveforms directly; rely on the catalog text and numbers.

## Timeline capabilities (schema version 2)

The project uses **multi-track** timelines:

- Any number of tracks of type `video`, `audio`, and `caption`.
- Each **clip** uses:
  - `id` (string, unique)
  - `source` — exactly `footage/<filename>` from the catalog
  - `source_in`, `source_out` — trim range in the source file (seconds)
  - `timeline_start` — where the clip begins on the timeline (seconds); **do not set on speech EDL clips** (see below)
  - `created_by` — use `"ai"`
  - Optional: `group_id` (string) to link related clips
  - Optional: `speed`, `volume`, `zoom` (video)
  - Optional audio fades (seconds): `audio_fade_in`, `audio_fade_out` on video and audio clips
  - Optional video fades (seconds): `video_fade_in`, `video_fade_out` on video clips only
  - Optional cut to the next video clip: `transition_out`: `{ "type": "dissolve" | "crossfade", "duration": <seconds> }` on a video clip. Export overlaps those two clips by that duration (the joined picture is shorter by that amount) and overlaps their audio by the same amount so sound stays in sync. Preview plays a hard cut; the overlap is export only.
  - Optional on **audio tracks** (not clips): `duck_under_track_id` (another audio track id), `duck_gain` (0–1, default 0.25). While this track overlaps clips on that track, its level eases down to duck_gain and back (short attack and release). Outside the overlap the level stays unchanged.
  - Do **not** use fade, transition, or ducking fields you were not told are supported; omit when unsure
  - Optional on **video** clips: `audio_source` — `"embedded"` (default) or `"detached"`:
    - `embedded`: mix the clip's own audio in the usual way.
    - `detached`: mute embedded audio for that video segment (use when audio comes only from another track).
  - Optional: `caption` on video clips as a short editorial note (not necessarily burned-in text)

**Caption track** clips need `text` (on-screen string) plus timing fields like video/audio.

**Video gaps**: You may leave picture holes on **video** tracks by advancing `timeline_start` where the brief needs them.

## Speech editing (code-owned layout — read carefully)

### EDL output only (no timeline math on voice)

On the primary **speech / voiceover** audio track you output an **edit decision list (EDL)** only:

- Set `"speech_layout_mode": "edl"` on that track.
- List clips **in final playback order** in the `clips` array (sentences, phrases, or word groups — whatever unit serves the brief).
- Each unit must include: `id`, `source`, `source_in`, `source_out`, `created_by: "ai"`, plus:
  - `cut_intent`: `{ "start": "complete"|"fragment", "end": "complete"|"fragment"|"abrupt"|"fade", "reason": "<why>" }`
  - optional top-level `reason` if clearer than nesting in `cut_intent`.
- **Forbidden on speech EDL clips:** `timeline_start`, `timeline_end`, or any field that encodes cumulative timeline position. Layout is computed locally (`build_speech_layout`) after energy-based trim refinement.
- Do **not** shorten `source_out` / pull `source_in` to create silence between lines — that is never pacing.

**Video / captions tied to speech:** `speech_bind: "<speech_clip_id>"` so picture/captions ripple with speech. Independent b-roll and music/sfx keep normal `timeline_start` on their own tracks.

**Music / sfx / non-voice audio:** use ordinary clips with `timeline_start` on separate tracks (not EDL).

### Self-correction and false-start exclusion (strict)

Before choosing spans, scan transcripts for speaker **flubs** and **do not use** those ranges in any clip:

- Mid-sentence restarts, stuttered re-takes, aborted lines, retracted statements.
- Phrases like: "Wait, no…", "Let me rephrase…", "Actually—", "I was— I mean…", "Sorry, scratch that", "Hang on".
- The **first** false attempt in a pair — keep only the **final clean** wording the speaker settled on.
- Apply the same rule when picking **synced video** (`speech_bind`): video must match the clean speech unit, not the botched take.

If the only material in a file is false starts, omit that file.

### Pacing via `gap_after` only

Express breath / beat **only** with `gap_after` on each speech clip except the last:

- `{ "mode": "continuous" }` — hard join (default).
- `{ "mode": "pause", "duration_s": <seconds>, "fill": "room_tone"|"silence" }` — intentional pause.

Never invent pacing with mystery timeline holes or by trimming word tails.

### What the codebase handles (do not duplicate)

After your EDL is accepted, local code automatically:

- Refines `source_in` / `source_out` on **word boundaries** and **acoustic energy** (decay tails, not just Whisper `word.end`).
- Applies short speech-safe fades and optional join crossfades.
- Lays clips **contiguously** (plus approved `gap_after` pauses only).
- Validates that accidental gaps are not introduced by trims.

You still choose **which words** and **source times** from the catalog; pick coarse spans on word boundaries. Do not cut inside a word.

`target_length_seconds` is a **soft** hint — prefer a readable cut; add `length_note` if you stretch far from the brief.

**Video gaps (picture only):** you may leave holes on **video** tracks with `timeline_start` where the brief needs them.

**Video without audio:** valid; use `audio_source: detached` or separate audio-track clips.

You decide which files to use and how to layer them. Omit files that do not fit the brief.

## Output format

Return **only** valid JSON (no markdown fences) with:

- `schema_version`: 2
- `name`: short slug
- `brief`: repeat the user's brief
- `target_length_seconds`: number (soft length hint for the edit)
- `length_note`: optional string when you intentionally miss the brief length
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
        f"Target length hint: about {target} seconds (soft — prioritize how the edit reads)."
        if target
        else "Pick target_length_seconds as a soft hint from the brief."
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


def response_text_and_stop(response: object) -> tuple[str, str | None]:
    """Join every text block. Thinking blocks are not timeline JSON."""
    parts: list[str] = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) != "text":
            continue
        chunk = getattr(block, "text", "") or ""
        if chunk:
            parts.append(chunk)
    stop = getattr(response, "stop_reason", None)
    return "\n".join(parts), (str(stop) if stop else None)


def _first_balanced_json_object(text: str, start: int) -> str:
    """Slice the object that begins at start, respecting strings and escapes."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError(
        "JSON object was cut off before it closed "
        "(the reply may have hit the token limit)"
    )


def parse_plan_json(text: str) -> dict:
    """
    Pull the first JSON object out of a model reply.
    Drops markdown fences and any prose before or after the object.
    """
    if not text or not str(text).strip():
        raise ValueError("model returned no JSON text")
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "")
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("No JSON object in model response")
    blob = _first_balanced_json_object(cleaned, start)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Plan JSON could not be parsed: {exc}") from exc
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


def save_raw_planner_response(
    text: str,
    *,
    stop_reason: str | None,
    attempt: str,
) -> Path:
    """Atomic text dump so a bad reply can be inspected without another API call."""
    debug_dir = Path.cwd() / "plans" / "_planner_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    path = debug_dir / f"{stamp}_{attempt}.txt"
    body = f"stop_reason: {stop_reason}\n\n{text}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    return path


def stop_reason_note(stop_reason: str | None) -> str:
    if stop_reason == "max_tokens":
        return (
            f"Planner hit max_tokens ({PLANNER_MAX_TOKENS}) and the reply was cut off "
            "(stop_reason=max_tokens)."
        )
    if stop_reason:
        return f"stop_reason={stop_reason}."
    return "stop_reason was not reported."


def invalid_plan_message(
    exc: BaseException,
    stop_reason: str | None,
    raw_path: Path,
    *,
    attempt: str,
) -> str:
    return (
        f"Invalid plan JSON ({attempt}): {exc}. {stop_reason_note(stop_reason)} "
        f"Raw response saved to {raw_path}."
    )


def build_json_retry_user_prompt(previous_text: str, stop_reason: str | None) -> str:
    """
    One short follow-up. Does not include the media catalog.
    The previous reply is clipped so this call stays cheap.
    """
    clipped = previous_text or ""
    if len(clipped) > 8000:
        clipped = clipped[:4000] + "\n...\n" + clipped[-4000:]
    return (
        "The previous reply was not a usable timeline JSON object. "
        f"{stop_reason_note(stop_reason)} "
        "Reply with one JSON object only. No markdown fences and no explanation. "
        "If the reply was cut off, return a shorter valid schema_version 2 timeline.\n\n"
        "Previous reply:\n"
        f"{clipped}"
    )


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
    acfg = load_settings(Path.cwd())
    detect_and_normalize_edl(v2)
    if acfg.get("enabled", True):
        v2, _report = refine_timeline_audio_cuts(v2, settings=acfg)
    build_speech_layout(v2)
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
    detect_and_normalize_edl(plan)
    acfg = load_settings(Path.cwd())
    if acfg.get("enabled", True):
        plan, _report = refine_timeline_audio_cuts(plan, settings=acfg)
    build_speech_layout(plan)
    errors, _warn = validate_plan_data(plan, target)
    if errors:
        raise ValueError(errors)
    return plan


def validate_plan_parsed(plan: dict, brief: str, target: float | None) -> list[str]:
    """Unified validation errors for fix-pass."""
    if is_v2(plan):
        # Speech EDL clips omit timeline_start until layout is built (same as finalize).
        detect_and_normalize_edl(plan)
        acfg = load_settings(Path.cwd())
        if acfg.get("enabled", True):
            plan, _report = refine_timeline_audio_cuts(plan, settings=acfg)
        build_speech_layout(plan)
        errs, _ = validate_plan_data(plan, target)
        return errs
    return validate_segments(plan.get("segments") or [], target)


def call_claude(
    model: str,
    system: str | list,
    user: str | list,
    *,
    api_key: str | None = None,
) -> tuple[str, object, str | None]:
    import anthropic

    key = (api_key or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=model,
        max_tokens=PLANNER_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text, stop_reason = response_text_and_stop(response)
    return text, response.usage, stop_reason


def _usage_tokens(usage: object) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def record_planner_usage(
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> dict:
    """Add this run to today's total in index/planner_usage.json (atomic write)."""
    path = planner_usage_path()
    data = load_json(path)
    if not isinstance(data, dict):
        data = {}
    days = data.get("days")
    if not isinstance(days, dict):
        days = {}
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bucket = days.get(day)
    if not isinstance(bucket, dict):
        bucket = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "runs": 0}
    bucket["input_tokens"] = int(bucket.get("input_tokens") or 0) + int(input_tokens)
    bucket["output_tokens"] = int(bucket.get("output_tokens") or 0) + int(output_tokens)
    bucket["cost_usd"] = round(float(bucket.get("cost_usd") or 0) + float(cost_usd), 6)
    bucket["runs"] = int(bucket.get("runs") or 0) + 1
    days[day] = bucket
    data["days"] = days
    save_json_atomic(path, data)
    return bucket


def print_usage(usage: object, model: str) -> None:
    if usage is None:
        return
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    est = inp * INPUT_USD_PER_TOKEN + out * OUTPUT_USD_PER_TOKEN
    print(f"Tokens ({model}): input={inp} output={out}  (~${est:.4f} estimated)")


def _parse_or_retry_plan(
    text: str,
    stop_reason: str | None,
    *,
    model_used: str,
    system_prompt: str | list,
    api_key: str | None,
    total_usage: dict,
    budget: RunBudget | None = None,
) -> dict:
    """Parse the reply. On failure, one cheap retry that does not resend the catalog."""
    try:
        return parse_plan_json(text)
    except (json.JSONDecodeError, ValueError) as first_error:
        raw_path = save_raw_planner_response(
            text, stop_reason=stop_reason, attempt="first"
        )
        retry_user = build_json_retry_user_prompt(text, stop_reason)
        est_in = estimate_tokens(retry_user) + estimate_tokens(
            content_as_text(system_prompt)
        )
        if budget is not None and not budget.allow(
            est_input=est_in, est_output=OUTPUT_TOKEN_GUESS
        ):
            raise ValueError(
                invalid_plan_message(
                    first_error, stop_reason, raw_path, attempt="first reply"
                )
                + f" Stopped before a retry ({budget.stop_reason})."
            )
        try:
            retry_text, usage2, stop2 = call_claude(
                model_used, system_prompt, retry_user, api_key=api_key
            )
        except Exception as exc:
            raise RuntimeError(
                "Planner API error on JSON retry: "
                f"{exc}. {invalid_plan_message(first_error, stop_reason, raw_path, attempt='first reply')}"
            ) from exc
        in2, out2 = _usage_tokens(usage2)
        total_usage["input_tokens"] += in2
        total_usage["output_tokens"] += out2
        if budget is not None:
            budget.note_call(in2, out2)
        try:
            return parse_plan_json(retry_text)
        except (json.JSONDecodeError, ValueError) as retry_error:
            raw2 = save_raw_planner_response(
                retry_text, stop_reason=stop2, attempt="retry"
            )
            raise ValueError(
                invalid_plan_message(
                    first_error, stop_reason, raw_path, attempt="first reply"
                )
                + " "
                + invalid_plan_message(
                    retry_error, stop2, raw2, attempt="retry"
                )
            ) from retry_error


def _excluded_takes_prompt(excluded_take_ids: list[str] | None) -> str:
    if not excluded_take_ids:
        return ""
    from planner_preflight import excluded_time_ranges

    ranges = excluded_time_ranges(Path.cwd(), excluded_take_ids)
    if not ranges:
        return ""
    lines = [
        "## User-discarded take attempts (never use these source time ranges)",
    ]
    for name in sorted(ranges.keys()):
        for t0, t1 in ranges[name]:
            lines.append(f"- footage/{name}: {t0:.2f}s–{t1:.2f}s")
    return "\n".join(lines)


def resolve_planner_clip_scope(
    clip_filenames: list[str] | None,
    primary_source_file: str | None,
) -> list[str] | None:
    """When primary_source_file is set, catalog and agent are restricted to that basename."""
    if primary_source_file and str(primary_source_file).strip():
        return [Path(primary_source_file.strip()).name]
    return clip_filenames


def prepare_planner_context(
    brief: str,
    *,
    clip_filenames: list[str] | None = None,
    primary_source_file: str | None = None,
    imitate_style_id: str | None = None,
    root: Path | None = None,
) -> dict:
    """
    Build the compact catalog and a cost estimate. Does not call the model.
    """
    t0 = time.perf_counter()
    project = root or Path.cwd()
    limits = load_planner_settings(project)
    imitate_profile = None
    if imitate_style_id:
        imitate_profile = load_style_profile(project, imitate_style_id)
    system_prompt = build_system_prompt(imitate_profile=imitate_profile)
    effective_clips = resolve_planner_clip_scope(clip_filenames, primary_source_file)
    scope = "selected" if effective_clips else "all"
    catalog, cat_warnings = build_media_catalog(
        project,
        scope=scope,
        only_basenames=effective_clips,
    )
    if not catalog:
        raise RuntimeError(
            "No media files in footage/. Add clips (video and/or audio), then run analysis."
        )
    rows, omitted, unanalyzed = select_compact(
        catalog,
        brief,
        int(limits["catalog_token_budget"]),
    )
    catalog_ms = int((time.perf_counter() - t0) * 1000)
    if not rows:
        # Estimate can report this. generate_plan turns it into an error.
        return {
            "limits": limits,
            "system": [],
            "user": [],
            "rows": [],
            "omitted": omitted,
            "unanalyzed": unanalyzed,
            "catalog_build_ms": catalog_ms,
            "input_tokens": 0,
            "output_tokens_guess": 0,
            "est_cost_usd": 0.0,
            "confirm": False,
            "model": limits["edit_model"],
            "file_count": 0,
            "mode": "draft",
        }
    cat_text = catalog_block(rows, omitted=omitted, unanalyzed=unanalyzed)
    if cat_warnings:
        cat_text += "\nCatalog warnings:\n" + "\n".join(f"- {w}" for w in cat_warnings)
    target = parse_target_seconds(brief)
    target_line = (
        f"Target length hint: about {target} seconds (soft — prioritize how the edit reads)."
        if target
        else "Pick target_length_seconds as a soft hint from the brief."
    )
    brief_text = (
        f"User brief:\n{brief}\n\n{target_line}\n\n"
        "Return the timeline JSON object only (schema_version 2, see system instructions)."
    )
    system = cached_system_blocks(system_prompt)
    user = user_content_blocks(cat_text, brief_text)
    input_tokens = estimate_tokens(content_as_text(system) + content_as_text(user))
    cost = estimate_cost_usd(input_tokens, OUTPUT_TOKEN_GUESS, tier="edit")
    return {
        "limits": limits,
        "system": system,
        "user": user,
        "rows": rows,
        "omitted": omitted,
        "unanalyzed": unanalyzed,
        "catalog_build_ms": catalog_ms,
        "input_tokens": input_tokens,
        "output_tokens_guess": OUTPUT_TOKEN_GUESS,
        "est_cost_usd": round(cost, 4),
        "confirm": cost >= float(limits["confirm_above_usd"]),
        "model": limits["edit_model"],
        "file_count": len(rows),
        "mode": "draft",
    }


def _attach_run_meta(plan: dict, meta: dict) -> dict:
    out = dict(plan)
    out["planner_run"] = meta
    return out


def generate_plan(
    brief: str,
    *,
    api_key: str | None = None,
    clip_filenames: list[str] | None = None,
    primary_source_file: str | None = None,
    excluded_take_ids: list[str] | None = None,
    imitate_style_id: str | None = None,
    require_merged_index: bool = True,
    mode: str = "draft",
) -> tuple[dict, str, dict]:
    """
    Draft mode: one edit-model call on the compact catalog, plus at most
    a cheap JSON retry and one repair that does not resend unrelated files.
    Full mode is not built yet.
    require_merged_index is kept so older callers still import; unanalyzed
    files are never sent either way.
    """
    del require_merged_index  # behavior is always "do not send unanalyzed files"
    load_dotenv()
    if (mode or "draft").lower() != "draft":
        raise RuntimeError(
            "Full mode is not available yet. Use Draft. The agent loop is a later step."
        )

    brief_for_model = brief
    excluded_block = _excluded_takes_prompt(excluded_take_ids)
    if excluded_block:
        brief_for_model = f"{brief.rstrip()}\n\n{excluded_block}"
    ctx = prepare_planner_context(
        brief_for_model,
        clip_filenames=clip_filenames,
        primary_source_file=primary_source_file,
        imitate_style_id=imitate_style_id,
    )
    if not ctx["rows"]:
        joined = ", ".join(ctx["unanalyzed"]) if ctx["unanalyzed"] else "(none)"
        raise RuntimeError(
            "No analyzed media to plan with. Analyze now: " + joined
        )
    limits = ctx["limits"]
    budget = RunBudget(limits)
    model_used = str(limits["edit_model"])
    fallback = DEFAULT_MODEL if model_used == DEFAULT_MODEL_ENV else None
    model_candidates = [model_used]
    if fallback and fallback not in model_candidates:
        model_candidates.append(fallback)

    total_usage: dict = {
        "input_tokens": 0,
        "output_tokens": 0,
        "catalog_build_ms": ctx["catalog_build_ms"],
        "model_call_ms": 0,
        "validation_ms": 0,
        "file_count": ctx["file_count"],
        "omitted_count": ctx["omitted"],
        "unanalyzed": ctx["unanalyzed"],
        "mode": "draft",
        "tier": "edit",
    }

    if not budget.allow(
        est_input=int(ctx["input_tokens"]),
        est_output=OUTPUT_TOKEN_GUESS,
        images=0,
    ):
        raise RuntimeError(
            "Planner stopped before the model call "
            f"({budget.stop_reason}). Raise the limit in Settings or shorten the brief."
        )

    text: str | None = None
    usage = None
    stop_reason: str | None = None
    model_t0 = time.perf_counter()
    for i, current_model in enumerate(model_candidates):
        try:
            text, usage, stop_reason = call_claude(
                current_model, ctx["system"], ctx["user"], api_key=api_key
            )
            model_used = current_model
            break
        except Exception as e:
            if i < len(model_candidates) - 1:
                continue
            raise RuntimeError(f"Planner API error: {e}") from e
    total_usage["model_call_ms"] += int((time.perf_counter() - model_t0) * 1000)

    assert text is not None
    in1, out1 = _usage_tokens(usage)
    total_usage["input_tokens"] += in1
    total_usage["output_tokens"] += out1
    budget.note_call(in1, out1)

    plan = _parse_or_retry_plan(
        text,
        stop_reason,
        model_used=model_used,
        system_prompt=ctx["system"],
        api_key=api_key,
        total_usage=total_usage,
        budget=budget,
    )
    # Retry tokens were added inside _parse_or_retry_plan; keep the budget in sync
    # when the retry did not run (note_call already counted the first response only).
    budget.input_tokens = int(total_usage["input_tokens"])
    budget.output_tokens = int(total_usage["output_tokens"])

    run_group_id = str(uuid.uuid4())
    target = parse_target_seconds(brief) or plan.get("target_length_seconds")
    target = float(target) if isinstance(target, (int, float)) else None

    val_t0 = time.perf_counter()
    errors = validate_plan_parsed(plan, brief, target)
    total_usage["validation_ms"] += int((time.perf_counter() - val_t0) * 1000)
    budget_stop = None
    if errors:
        repair = build_repair_prompt(plan, errors, ctx["rows"])
        est_in = estimate_tokens(repair) + estimate_tokens(content_as_text(ctx["system"]))
        if not budget.allow(est_input=est_in, est_output=OUTPUT_TOKEN_GUESS):
            budget_stop = budget.stop_reason
        else:
            model_t0 = time.perf_counter()
            try:
                text, usage2, _fix_stop = call_claude(
                    model_used, ctx["system"], repair, api_key=api_key
                )
            except Exception as e:
                raise RuntimeError(f"Planner API error on fix pass: {e}") from e
            total_usage["model_call_ms"] += int((time.perf_counter() - model_t0) * 1000)
            in2, out2 = _usage_tokens(usage2)
            total_usage["input_tokens"] += in2
            total_usage["output_tokens"] += out2
            budget.note_call(in2, out2)
            try:
                plan = parse_plan_json(text)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Invalid fixed plan JSON: {e}") from e
            val_t0 = time.perf_counter()
            errors = validate_plan_parsed(plan, brief, target)
            total_usage["validation_ms"] += int((time.perf_counter() - val_t0) * 1000)
            if errors:
                raise ValueError(errors)

    if budget_stop:
        plan_v2 = plan
    elif is_v2(plan):
        plan_v2 = finalize_v2_direct(plan, brief, run_group_id)
    else:
        plan_v2 = finalize_v2_from_segments(plan, brief, run_group_id)

    cost = round(estimate_cost_usd(
        int(total_usage["input_tokens"]),
        int(total_usage["output_tokens"]),
        tier="edit",
    ), 4)
    day = record_planner_usage(
        input_tokens=int(total_usage["input_tokens"]),
        output_tokens=int(total_usage["output_tokens"]),
        cost_usd=cost,
    )
    meta = {
        "mode": "draft",
        "model": model_used,
        "input_tokens": total_usage["input_tokens"],
        "output_tokens": total_usage["output_tokens"],
        "cost_usd": cost,
        "timings_ms": {
            "catalog_build": total_usage["catalog_build_ms"],
            "model_call": total_usage["model_call_ms"],
            "validation": total_usage["validation_ms"],
        },
        "budget_stop": budget_stop,
        "omitted_files": ctx["omitted"],
        "unanalyzed": ctx["unanalyzed"],
        "validation_errors": errors if budget_stop else [],
        "day_total": day,
    }
    plan_v2 = _attach_run_meta(plan_v2, meta)
    total_usage["model"] = model_used
    total_usage["cost_usd"] = cost
    total_usage["budget_stop"] = budget_stop
    total_usage["day_total"] = day
    total_usage["timings_ms"] = meta["timings_ms"]
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
