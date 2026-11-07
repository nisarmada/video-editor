"""
Multi-step agentic speech planner: tool calls + audit self-correction loop.

Tools wrap catalog inspection, EDL layout, cut audit, boundary nudges, and plan save.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

_SCRIPTS = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS.parent
import sys

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from audio_cut_refine import load_settings, refine_timeline_audio_cuts  # noqa: E402
from backend.media_catalog import build_media_catalog  # noqa: E402
from planner_speech_qa import audit_speech_edl_false_starts  # noqa: E402
from speech_cut_audit import MIN_DECAY_RETAINED_MS, audit_timeline_speech_cuts  # noqa: E402
from speech_edit_quality import flatten_words  # noqa: E402
from speech_layout import (  # noqa: E402
    build_speech_layout,
    detect_and_normalize_edl,
    validate_primary_video_packing,
    validate_timeline_speech_layout,
)
from plan import resolve_planner_clip_scope  # noqa: E402
from planner_preflight import excluded_time_ranges, take_attempt_id  # noqa: E402
from validate_plan import validate_plan_data  # noqa: E402
from index_cache import load_json, transcript_path  # noqa: E402

ProgressFn = Callable[[str], None] | None

DEFAULT_MAX_CORRECTION_LOOPS = 3
AGENT_SYSTEM = """You are a speech-edit planner agent. Use tools only — do not invent JSON in plain text.

Workflow:
1. list_and_inspect_media — pick clean takes; skip false-start / abandoned spans.
2. generate_speech_edl — ordered EDL items (source_in/out only, no timeline_start on speech).
3. audit_edl_cuts — must pass before finalize.
4. If audit reports decay, gap, click, or false-start issues: nudge_or_replace_cut, then generate_speech_edl again.
5. finalize_plan when audit passes.

Speech clips need cut_intent and gap_after where needed. Never set timeline_start on speech EDL clips.

## False starts and corrected takes (hard rule)

- NEVER use transcript spans marked abandoned_sentence, is_restart, or listed in false_start_flags.
- When a speaker retracts or corrects (“wait—”, “let me—”, “actually—”, “I mean—”), use ONLY the final clean wording after the correction.
- If list_and_inspect_media shows multiple takes on one file, prefer the last complete take in each corrected pair.
- audit_edl_cuts will fail if any EDL span overlaps a flagged false start — fix before finalize.

## Single-source mode (when the user message says single_source_file)

- All EDL clips MUST come from that one footage/ file. Edit by pruning bad takes only; do not pull audio from other files.
- Picture may still come from other video files, but voice must stay on the single source."""

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_and_inspect_media",
        "description": "Indexed metadata, transcript excerpts, and false-start flags for footage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "clip_filenames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional basename filter; omit for all analyzed files.",
                }
            },
        },
    },
    {
        "name": "generate_speech_edl",
        "description": "Build candidate v2 timeline from ordered EDL items and run speech layout.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
                "track_id": {"type": "string", "default": "A1"},
                "track_label": {"type": "string", "default": "Voice"},
                "edl_items": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "gap_policy": {
                    "type": "object",
                    "description": "Default gap_after for items that omit it",
                },
            },
            "required": ["edl_items"],
        },
    },
    {
        "name": "audit_edl_cuts",
        "description": "Cut quality report: decay, gaps, clicks, false-start violations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timeline_json": {"type": "object"},
            },
            "required": ["timeline_json"],
        },
    },
    {
        "name": "nudge_or_replace_cut",
        "description": "Adjust one clip boundary or gap policy after a failed audit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timeline_json": {"type": "object"},
                "clip_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": [
                        "extend_tail_ms",
                        "trim_out_ms",
                        "set_gap_after",
                        "set_source_out",
                    ],
                },
                "ms": {"type": "number"},
                "source_out": {"type": "number"},
                "gap_after": {"type": "object"},
            },
            "required": ["timeline_json", "clip_id", "action"],
        },
    },
    {
        "name": "finalize_plan",
        "description": "Validate v2 schema and write plans/<stem>.json",
        "input_schema": {
            "type": "object",
            "properties": {
                "timeline_json": {"type": "object"},
                "save_as": {"type": "string"},
                "brief": {"type": "string"},
            },
            "required": ["timeline_json", "save_as"],
        },
    },
]


class AgentSession:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.timeline: dict[str, Any] | None = None
        self.words_by_source: dict[str, list[dict]] = {}
        self.inspection: dict[str, Any] | None = None
        self.last_audit: dict[str, Any] | None = None
        self.save_as: str | None = None
        self.brief: str = ""
        self.group_id = str(uuid.uuid4())
        self.primary_source_file: str | None = None
        self.excluded_take_ids: list[str] = []
        self.excluded_ranges: dict[str, list[tuple[float, float]]] = {}

    def allowed_speech_source(self) -> str | None:
        if not self.primary_source_file:
            return None
        return f"footage/{Path(self.primary_source_file.strip()).name}"

    def effective_clip_filter(self, clip_filenames: list[str] | None) -> list[str] | None:
        return resolve_planner_clip_scope(clip_filenames, self.primary_source_file)


def _overlaps_excluded(
    source: str,
    src_in: float,
    src_out: float,
    ranges: dict[str, list[tuple[float, float]]],
) -> bool:
    name = Path(source.replace("footage/", "")).name
    for t0, t1 in ranges.get(name, []):
        if src_out > t0 + 0.02 and src_in < t1 - 0.02:
            return True
    return False


def _progress(cb: ProgressFn, message: str) -> None:
    if cb:
        cb(message)


def _load_words_by_source(root: Path, sources: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for src in sources:
        name = Path(src.replace("footage/", "")).name
        p = root / "footage" / name
        if not p.is_file():
            p2 = root / src.lstrip("/")
            p = p2 if p2.is_file() else p
        tr = load_json(transcript_path(p))
        out[src] = flatten_words(tr if isinstance(tr, dict) else None)
    return out


def _false_start_flags_for_entry(entry: dict) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for take in entry.get("takes") or []:
        if not isinstance(take, dict):
            continue
        if take.get("abandoned_sentence") or take.get("is_restart"):
            flags.append(
                {
                    "take_index": take.get("take_index"),
                    "start": take.get("start"),
                    "end": take.get("end"),
                    "abandoned_sentence": bool(take.get("abandoned_sentence")),
                    "is_restart": bool(take.get("is_restart")),
                    "text_preview": (take.get("text") or "")[:80],
                }
            )
    return flags


def list_and_inspect_media(
    session: AgentSession,
    *,
    clip_filenames: list[str] | None = None,
) -> dict[str, Any]:
    only = session.effective_clip_filter(clip_filenames)
    scope = "selected" if only else "all"
    entries, warnings = build_media_catalog(
        session.root,
        scope=scope,
        only_basenames=only,
    )
    files: list[dict[str, Any]] = []
    for e in entries:
        if (e.get("analysis") or {}).get("merged_index") != "complete":
            continue
        file_id = str(e.get("id") or "")
        takes_rows = e.get("takes") if isinstance(e.get("takes"), list) else []
        excluded_ids: list[str] = []
        for row in takes_rows:
            if not isinstance(row, dict):
                continue
            tid = take_attempt_id(file_id, int(row.get("take_index", 0)))
            if tid in session.excluded_take_ids:
                excluded_ids.append(tid)
        files.append(
            {
                "id": e.get("id"),
                "kind": e.get("kind"),
                "duration_seconds": e.get("duration_seconds"),
                "transcript_segments": e.get("transcript_segments") or [],
                "takes_summary": e.get("takes_summary"),
                "false_start_flags": _false_start_flags_for_entry(e),
                "audio_perception_summary": e.get("audio_perception_summary"),
                "excluded_take_ids": excluded_ids,
            }
        )
    payload: dict[str, Any] = {"files": files, "warnings": warnings}
    if session.primary_source_file:
        payload["single_source_mode"] = True
        payload["primary_source_file"] = session.allowed_speech_source()
    session.inspection = payload
    return session.inspection


def _default_gap(gap_policy: dict | None) -> dict[str, Any]:
    if isinstance(gap_policy, dict) and gap_policy:
        return gap_policy
    return {"mode": "continuous"}


def generate_speech_edl(
    session: AgentSession,
    *,
    edl_items: list[dict],
    gap_policy: dict | None = None,
    brief: str | None = None,
    track_id: str = "A1",
    track_label: str = "Voice",
) -> dict[str, Any]:
    if brief:
        session.brief = brief
    allowed_src = session.allowed_speech_source()
    default_gap = _default_gap(gap_policy)
    clips: list[dict] = []
    sources: set[str] = set()
    for i, item in enumerate(edl_items):
        if not isinstance(item, dict):
            continue
        clip = copy.deepcopy(item)
        clip.setdefault("id", f"s{i + 1}")
        clip.setdefault("created_by", "ai")
        clip.setdefault("group_id", session.group_id)
        clip.setdefault("cut_intent", {"start": "complete", "end": "complete"})
        if "gap_after" not in clip and i + 1 < len(edl_items):
            clip["gap_after"] = copy.deepcopy(default_gap)
        src = clip.get("source")
        if isinstance(src, str):
            if not src.startswith("footage/"):
                clip["source"] = f"footage/{Path(src).name}"
                src = clip["source"]
            if allowed_src and src != allowed_src:
                return {
                    "error": (
                        f"single-source mode: clip {clip.get('id')} uses {src!r}; "
                        f"only {allowed_src!r} is allowed for speech."
                    ),
                }
            try:
                si = float(clip.get("source_in", 0))
                so = float(clip.get("source_out", si))
            except (TypeError, ValueError):
                si, so = 0.0, 0.0
            if session.excluded_ranges and _overlaps_excluded(
                src, si, so, session.excluded_ranges
            ):
                return {
                    "error": (
                        f"clip {clip.get('id')} overlaps a user-discarded take "
                        f"({src} {si:.2f}–{so:.2f}s)."
                    ),
                }
            sources.add(src)
        clips.append(clip)

    timeline: dict[str, Any] = {
        "schema_version": 2,
        "brief": session.brief or brief or "",
        "target_length_seconds": None,
        "created_by": "ai",
        "tracks": [
            {
                "id": track_id,
                "type": "audio",
                "label": track_label,
                "speech_layout_mode": "edl",
                "clips": clips,
            }
        ],
    }
    session.words_by_source.update(_load_words_by_source(session.root, sources))
    detect_and_normalize_edl(timeline)
    acfg = load_settings(session.root)
    if acfg.get("enabled", True):
        timeline, _report = refine_timeline_audio_cuts(
            timeline, root=session.root, settings=acfg
        )
    build_speech_layout(timeline)
    session.timeline = timeline
    return {"timeline": timeline, "clip_count": len(clips)}


def audit_edl_cuts(
    session: AgentSession,
    *,
    timeline_json: dict | None = None,
) -> dict[str, Any]:
    tl = timeline_json if timeline_json is not None else session.timeline
    if not isinstance(tl, dict):
        return {"pass": False, "error": "no timeline"}
    tl = copy.deepcopy(tl)
    cut_audit = audit_timeline_speech_cuts(tl)
    if not session.words_by_source:
        sources = {
            str(c.get("source"))
            for tr in tl.get("tracks") or []
            if tr.get("type") == "audio"
            for c in tr.get("clips") or []
            if isinstance(c, dict) and c.get("source")
        }
        session.words_by_source.update(_load_words_by_source(session.root, sources))
    false_starts = audit_speech_edl_false_starts(tl, session.words_by_source)
    layout_errors = validate_timeline_speech_layout(tl)
    layout_errors.extend(validate_primary_video_packing(tl))

    warnings: list[str] = []
    if cut_audit.get("summary"):
        warnings.append(str(cut_audit["summary"]))
    for line in false_starts:
        warnings.append(line)
    for err in layout_errors:
        warnings.append(err)

    decay_issues: list[dict] = []
    click_issues: list[dict] = []
    gap_issues: list[dict] = []
    for b in cut_audit.get("boundaries") or []:
        if b.get("edge") != "out":
            continue
        probs = b.get("problems") or []
        if "may_clip_ending" in probs:
            m = b.get("metrics") or {}
            decay_issues.append(
                {
                    "clip_id": b.get("clip_id"),
                    "decay_retained_ms": m.get("decay_retained_ms"),
                }
            )
        if "high_click" in probs:
            click_issues.append({"clip_id": b.get("clip_id")})
        if "unexpected_gap" in probs:
            gap_issues.append({"clip_id": b.get("clip_id")})

    passed = (
        cut_audit.get("problem_count", 0) == 0
        and not false_starts
        and not layout_errors
    )
    report = {
        "pass": passed,
        "problem_count": cut_audit.get("problem_count", 0),
        "false_start_violations": false_starts,
        "layout_errors": layout_errors,
        "decay_issues": decay_issues,
        "gap_issues": gap_issues,
        "click_issues": click_issues,
        "boundaries": cut_audit.get("boundaries") or [],
        "warnings": warnings,
    }
    session.last_audit = report
    if isinstance(timeline_json, dict):
        session.timeline = copy.deepcopy(timeline_json)
    return report


def nudge_or_replace_cut(
    session: AgentSession,
    *,
    timeline_json: dict,
    clip_id: str,
    action: str,
    ms: float | None = None,
    source_out: float | None = None,
    gap_after: dict | None = None,
) -> dict[str, Any]:
    tl = copy.deepcopy(timeline_json)
    found = False
    for tr in tl.get("tracks") or []:
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict) or str(clip.get("id")) != clip_id:
                continue
            found = True
            si = float(clip.get("source_in", 0))
            so = float(clip.get("source_out", si))
            if action == "extend_tail_ms":
                clip["source_out"] = round(so + max(0.0, float(ms or 50)) / 1000.0, 4)
            elif action == "trim_out_ms":
                clip["source_out"] = round(
                    max(si + 0.05, so - max(0.0, float(ms or 30)) / 1000.0), 4
                )
            elif action == "set_source_out" and source_out is not None:
                clip["source_out"] = round(float(source_out), 4)
            elif action == "set_gap_after" and gap_after is not None:
                clip["gap_after"] = copy.deepcopy(gap_after)
            # Refresh decay metadata hint for audit
            q = clip.setdefault("speech_cut_quality", {})
            if action == "extend_tail_ms":
                cur = float(q.get("decay_retained_ms") or 0)
                q["decay_retained_ms"] = max(cur, MIN_DECAY_RETAINED_MS + 10)
            break
    if not found:
        return {"ok": False, "error": f"clip {clip_id} not found"}
    session.timeline = tl
    detect_and_normalize_edl(tl)
    acfg = load_settings(session.root)
    if acfg.get("enabled", True):
        tl, _ = refine_timeline_audio_cuts(
            tl,
            root=session.root,
            settings=acfg,
            clip_ids={clip_id},
        )
    build_speech_layout(tl)
    session.timeline = tl
    return {"ok": True, "timeline": tl}


def finalize_plan(
    session: AgentSession,
    *,
    timeline_json: dict,
    save_as: str,
    brief: str | None = None,
) -> dict[str, Any]:
    tl = copy.deepcopy(timeline_json)
    if brief:
        tl["brief"] = brief
        session.brief = brief
    stem = Path(save_as).stem
    session.save_as = stem
    target = tl.get("target_length_seconds")
    target = float(target) if isinstance(target, (int, float)) else None
    errors, warnings = validate_plan_data(tl, target)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    plans_dir = session.root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    out_path = plans_dir / f"{stem}.json"
    out_path.write_text(
        json.dumps(tl, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    session.timeline = tl
    return {
        "ok": True,
        "path": str(out_path.relative_to(session.root)),
        "warnings": warnings,
    }


def dispatch_tool(session: AgentSession, name: str, arguments: dict) -> Any:
    if name == "list_and_inspect_media":
        return list_and_inspect_media(
            session, clip_filenames=arguments.get("clip_filenames")
        )
    if name == "generate_speech_edl":
        return generate_speech_edl(
            session,
            edl_items=arguments.get("edl_items") or [],
            gap_policy=arguments.get("gap_policy"),
            brief=arguments.get("brief"),
            track_id=str(arguments.get("track_id") or "A1"),
            track_label=str(arguments.get("track_label") or "Voice"),
        )
    if name == "audit_edl_cuts":
        return audit_edl_cuts(
            session, timeline_json=arguments.get("timeline_json") or session.timeline
        )
    if name == "nudge_or_replace_cut":
        return nudge_or_replace_cut(session, **arguments)
    if name == "finalize_plan":
        return finalize_plan(session, **arguments)
    return {"error": f"unknown tool {name}"}


def _usage_add(total: dict, usage: Any) -> None:
    if usage is None:
        return
    total["input_tokens"] = int(total.get("input_tokens") or 0) + int(
        getattr(usage, "input_tokens", 0) or 0
    )
    total["output_tokens"] = int(total.get("output_tokens") or 0) + int(
        getattr(usage, "output_tokens", 0) or 0
    )


def run_agentic_plan(
    brief: str,
    *,
    save_as: str,
    root: Path | None = None,
    clip_filenames: list[str] | None = None,
    primary_source_file: str | None = None,
    excluded_take_ids: list[str] | None = None,
    api_key: str | None = None,
    max_correction_loops: int = DEFAULT_MAX_CORRECTION_LOOPS,
    on_progress: ProgressFn = None,
    client: Any | None = None,
    model: str = "claude-sonnet-5-5",
) -> tuple[dict, str, dict]:
    """
    Agentic planner: Anthropic tool-use loop with mandatory audit self-correction.
    Pass client= for tests (object with messages.create).
    """
    project = (root or Path.cwd()).resolve()
    session = AgentSession(project)
    session.brief = brief
    session.save_as = Path(save_as).stem
    session.primary_source_file = primary_source_file
    session.excluded_take_ids = [str(x) for x in (excluded_take_ids or []) if str(x).strip()]
    session.excluded_ranges = excluded_time_ranges(project, session.excluded_take_ids)
    effective_clips = session.effective_clip_filter(clip_filenames)

    usage_total: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "mode": "agentic",
        "correction_loops": 0,
        "tool_calls": 0,
    }

    if client is None:
        import anthropic

        key = (api_key or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=key)

    single_line = ""
    if primary_source_file:
        single_line = (
            f"\nsingle_source_file: {session.allowed_speech_source()}\n"
            "Use single-source mode for all speech EDL clips.\n"
        )
    if session.excluded_take_ids:
        single_line += (
            f"\nUser discarded take ids: {session.excluded_take_ids}\n"
            "Never cut speech from those attempt time ranges.\n"
        )
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Brief:\n{brief}\n\n"
                f"Save plan as: {session.save_as}\n"
                f"Clip filter: {effective_clips or 'all analyzed'}"
                f"{single_line}\n"
                "Execute the workflow with tools."
            ),
        }
    ]

    def one_model_turn(msgs: list[dict]) -> Any:
        return client.messages.create(
            model=model,
            max_tokens=4096,
            system=AGENT_SYSTEM,
            tools=TOOL_DEFINITIONS,
            messages=msgs,
        )

    correction = 0
    finalized = False

    while correction <= max_correction_loops and not finalized:
        if correction == 0:
            _progress(on_progress, "Scanning transcripts")
        else:
            _progress(on_progress, f"Self-correcting (pass {correction})")

        response = one_model_turn(messages)
        _usage_add(usage_total, getattr(response, "usage", None))

        while getattr(response, "stop_reason", None) == "tool_use":
            tool_blocks = [
                b
                for b in getattr(response, "content", []) or []
                if getattr(b, "type", None) == "tool_use"
            ]
            if not tool_blocks:
                break
            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict] = []
            for block in tool_blocks:
                usage_total["tool_calls"] = int(usage_total["tool_calls"]) + 1
                name = block.name
                args = block.input if isinstance(block.input, dict) else {}
                if name == "generate_speech_edl":
                    _progress(on_progress, "Drafting EDL")
                elif name == "audit_edl_cuts":
                    _progress(on_progress, "Auditioning acoustic cuts")
                elif name == "nudge_or_replace_cut":
                    _progress(on_progress, f"Adjusting clip {args.get('clip_id')}")
                elif name == "list_and_inspect_media":
                    _progress(on_progress, "Inspecting media index")
                elif name == "finalize_plan":
                    _progress(on_progress, "Finalizing plan")
                result = dispatch_tool(session, name, args)
                if name == "finalize_plan" and isinstance(result, dict) and result.get("ok"):
                    finalized = True
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            response = one_model_turn(messages)
            _usage_add(usage_total, getattr(response, "usage", None))

        if session.last_audit and session.last_audit.get("pass"):
            if session.timeline and not finalized:
                fin = finalize_plan(
                    session,
                    timeline_json=session.timeline,
                    save_as=session.save_as or "agent_plan",
                    brief=brief,
                )
                if fin.get("ok"):
                    finalized = True
            break

        if session.timeline is None:
            list_and_inspect_media(session, clip_filenames=effective_clips)
            break

        audit = audit_edl_cuts(session, timeline_json=session.timeline)
        usage_total["correction_loops"] = correction
        if audit.get("pass"):
            fin = finalize_plan(
                session,
                timeline_json=session.timeline,
                save_as=session.save_as or "agent_plan",
                brief=brief,
            )
            if fin.get("ok"):
                finalized = True
            break

        if correction >= max_correction_loops:
            break

        # Deterministic safety net when the model did not nudge
        decay = audit.get("decay_issues") or []
        if decay:
            cid = decay[0].get("clip_id")
            if cid:
                _progress(on_progress, f"Auto-nudge clip {cid}")
                nudge_or_replace_cut(
                    session,
                    timeline_json=session.timeline,
                    clip_id=str(cid),
                    action="extend_tail_ms",
                    ms=60,
                )
        messages.append(
            {
                "role": "user",
                "content": (
                    "audit_edl_cuts failed. You MUST call nudge_or_replace_cut "
                    f"then generate_speech_edl. Report: {json.dumps(audit, ensure_ascii=False)}"
                ),
            }
        )
        correction += 1

    if not session.timeline or not finalized:
        if session.timeline:
            fin = finalize_plan(
                session,
                timeline_json=session.timeline,
                save_as=session.save_as or "agent_plan",
                brief=brief,
            )
            if not fin.get("ok"):
                raise ValueError(fin.get("errors") or "finalize failed")
        else:
            raise RuntimeError("Agent did not produce a timeline")

    plan = session.timeline
    if not plan:
        raise RuntimeError("Missing plan after agent run")
    errors, _ = validate_plan_data(plan, plan.get("target_length_seconds"))
    if errors:
        raise ValueError(errors)
    layout_errs = validate_timeline_speech_layout(plan)
    layout_errs.extend(validate_primary_video_packing(plan))
    if layout_errs:
        raise ValueError(layout_errs)

    meta = {
        "mode": "agentic",
        "group_id": session.group_id,
        "correction_loops": usage_total.get("correction_loops", 0),
        "tool_calls": usage_total.get("tool_calls", 0),
        "last_audit": session.last_audit,
    }
    plan = {**plan, "planner_run": meta}
    return plan, session.group_id, usage_total


def run_scripted_agent(
    brief: str,
    *,
    save_as: str,
    root: Path,
    steps: list[dict[str, Any]],
    on_progress: ProgressFn = None,
) -> tuple[dict, str, dict]:
    """Test helper: run tool steps without the API."""
    session = AgentSession(root)
    session.brief = brief
    usage = {"mode": "agentic", "tool_calls": len(steps), "input_tokens": 0, "output_tokens": 0}
    for step in steps:
        name = step["tool"]
        args = step.get("args") or {}
        _progress(on_progress, step.get("progress") or name)
        dispatch_tool(session, name, args)
    if session.timeline is None:
        raise RuntimeError("script did not build timeline")
    fin = finalize_plan(
        session,
        timeline_json=session.timeline,
        save_as=save_as,
        brief=brief,
    )
    if not fin.get("ok"):
        raise ValueError(fin.get("errors"))
    return session.timeline, session.group_id, usage
