#!/usr/bin/env python3
"""
Ask Claude to build a timeline plan from clip indexes and a creative brief.
Usage: python scripts/plan.py --brief "30s reel, hook in first 2 seconds" --out plans/draft1.json
"""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from convert_v1_to_v2 import convert as v1_to_v2  # noqa: E402
from index_cache import load_json, merged_index_path  # noqa: E402
from timeline_format import get_track, is_v2  # noqa: E402
from validate_plan import validate_plan_data, validate_segments  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-5-20250514"
# User-facing default name; override with ANTHROPIC_PLAN_MODEL (e.g. claude-sonnet-5-5)
DEFAULT_MODEL_ENV = "claude-sonnet-5-5"

# Rough Sonnet-class $/token for console estimate (update if pricing changes)
INPUT_USD_PER_TOKEN = 3.0 / 1_000_000
OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000

SYSTEM_PROMPT = """You are a short-form vertical video editor (1080x1920, social reels).

You receive text summaries of raw clips (transcripts, silences, visual captions). You cannot see video.

Output ONLY valid JSON (no markdown fences) with this shape:
{
  "name": "short_slug",
  "brief": "<repeat the user brief>",
  "target_length_seconds": <number>,
  "segments": [
    {
      "source": "footage/<exact_filename_from_summaries>",
      "start": <seconds>,
      "end": <seconds>,
      "caption": "<short on-screen caption idea>",
      "reason": "<one line: why this cut is in the edit>"
    }
  ]
}

Rules:
- Use ONLY source filenames and time ranges that exist in the summaries.
- Each segment must be at least 0.3 seconds (end > start).
- Prefer cuts on speech boundaries (word/phrase starts and ends from transcripts).
- First segment must deliver a strong hook within the first ~2 seconds of the OUTPUT timeline.
- Total duration of all segments should match the brief's target length (within ~2 seconds).
- Mix clips for variety; avoid repeating the same quote twice unless the brief demands it.
- source paths must be exactly footage/<filename> as listed.
"""


def parse_target_seconds(brief: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?", brief, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*second", brief, re.I)
    if m:
        return float(m.group(1))
    return None


def footage_clips() -> list[Path]:
    root = Path.cwd() / "footage"
    if not root.is_dir():
        return []
    exts = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
    return sorted(p for p in root.iterdir() if p.suffix.lower() in exts and p.is_file())


def load_indexes() -> list[tuple[Path, dict]]:
    """Merged index/<stem>.json for each file in footage/."""
    loaded: list[tuple[Path, dict]] = []
    missing: list[str] = []
    for clip in footage_clips():
        path = merged_index_path(clip)
        data = load_json(path)
        if data is None:
            missing.append(clip.name)
            continue
        loaded.append((clip, data))
    if missing:
        print(
            "Warning: no merged index for: "
            + ", ".join(missing)
            + " (run index_clip.py on those clips).",
            file=sys.stderr,
        )
    return loaded


def format_transcript(transcript: dict) -> str:
    lines: list[str] = []
    for seg in transcript.get("segments") or []:
        start = seg.get("start", "?")
        end = seg.get("end", "?")
        text = (seg.get("text") or "").strip()
        if text:
            lines.append(f"  [{start}-{end}s] {text}")
    return "\n".join(lines) if lines else "  (no speech detected)"


def format_silences(index: dict) -> str:
    silences = index.get("silences")
    if silences is None:
        return "  (silence data not in index)"
    if not silences:
        return "  (no long silences detected)"
    return "\n".join(
        f"  [{s['start']}-{s['end']}s]" for s in silences if "start" in s
    )


def format_visual_captions(index: dict) -> str:
    caps = index.get("captions") or {}
    frames = caps.get("frames") if isinstance(caps, dict) else None
    if not frames:
        return "  (no AI frame captions — run caption_frames.py)"
    lines = []
    for f in frames:
        t = f.get("time_seconds", f.get("time", "?"))
        desc = f.get("description", "")
        stype = f.get("shot_type", "")
        mood = f.get("mood", "")
        subj = f.get("main_subject", "")
        lines.append(f"  [{t}s] {desc} | type={stype} | subject={subj} | mood={mood}")
    return "\n".join(lines)


def summarize_clip(clip_path: Path, index: dict) -> str:
    name = clip_path.name
    duration = index.get("duration_seconds", "?")
    source = f"footage/{name}"
    parts = [
        f"=== {name} ===",
        f"source path for timeline: {source}",
        f"duration: {duration}s",
        "Transcript:",
        format_transcript(index.get("transcript") or {}),
        "Silences:",
        format_silences(index),
        "Visual keyframe captions:",
        format_visual_captions(index),
    ]
    return "\n".join(parts)


def build_user_prompt(brief: str, summaries: list[str]) -> str:
    target = parse_target_seconds(brief)
    target_line = (
        f"Target length: about {target} seconds total."
        if target
        else "Infer a sensible target length from the brief."
    )
    return (
        f"Brief:\n{brief}\n\n{target_line}\n\n"
        "Available clips:\n\n"
        + "\n\n".join(summaries)
        + "\n\nReturn the timeline JSON only."
    )


def parse_plan_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, dict) or "segments" not in data:
        raise ValueError("Plan must be an object with a 'segments' array")
    return data


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


def finalize_v2_plan(v1_plan: dict, brief: str, run_group_id: str) -> dict:
    """Validate v1 segments from Claude, then convert to schema v2."""
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


def generate_plan(brief: str, *, api_key: str | None = None) -> tuple[dict, str, dict]:
    """
    Call Claude, validate, return v2 plan, group_id, and token usage tallies.
    Requires cwd = project root (footage/, index/).
    """
    load_dotenv()

    indexes = load_indexes()
    if not indexes:
        raise RuntimeError(
            "No merged indexes found. Add clips to footage/ and run index_clip.py."
        )

    summaries = [summarize_clip(clip, data) for clip, data in indexes]
    user_prompt = build_user_prompt(brief, summaries)

    requested = os.environ.get("ANTHROPIC_PLAN_MODEL", DEFAULT_MODEL_ENV)
    model_candidates = [requested]
    if requested == DEFAULT_MODEL_ENV and DEFAULT_MODEL not in model_candidates:
        model_candidates.append(DEFAULT_MODEL)

    total_usage = {"input_tokens": 0, "output_tokens": 0}
    text: str | None = None
    model_used = requested

    for i, current_model in enumerate(model_candidates):
        try:
            text, usage = call_claude(
                current_model, SYSTEM_PROMPT, user_prompt, api_key=api_key
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

    errors = validate_segments(plan.get("segments") or [], target)
    if errors:
        fix_prompt = (
            user_prompt
            + "\n\nYour previous JSON failed validation:\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\n\nReturn a corrected JSON object only."
        )
        try:
            text, usage2 = call_claude(
                model_used, SYSTEM_PROMPT, fix_prompt, api_key=api_key
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
        errors = validate_segments(plan.get("segments") or [], target)
        if errors:
            raise ValueError(errors)

    plan_v2 = finalize_v2_plan(plan, brief, run_group_id)
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
        print(f"\nPlan summary: {len(clips)} clips, {total:.2f}s source span")
        for i, clip in enumerate(clips):
            reason = clip.get("caption") or "(no reason)"
            src = Path(clip.get("source", "?")).name
            start = clip.get("source_in")
            end = clip.get("source_out")
            print(f"  {i + 1}. {src} [{start}-{end}s] — {reason}")
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
    args = parser.parse_args()

    try:
        plan_v2, run_group_id, total_usage = generate_plan(args.brief)
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
