"""
Take review payload for optional pre-flight before agentic / draft planning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.media_catalog import build_media_catalog  # noqa: E402
from plan import resolve_planner_clip_scope  # noqa: E402


def take_attempt_id(source_file: str, take_index: int) -> str:
    return f"{source_file}:{int(take_index)}"


def default_keep_attempt(attempt: dict, *, attempt_in_group: int, attempt_count: int) -> bool:
    if attempt.get("abandoned_sentence"):
        return False
    if attempt.get("is_restart") and attempt_in_group < attempt_count - 1:
        return False
    return True


def build_take_review_groups(
    root: Path,
    *,
    clip_filenames: list[str] | None = None,
    primary_source_file: str | None = None,
) -> list[dict[str, Any]]:
    """
    Group sentence attempts across analyzed speech files for UI review.
    Each attempt has id, default_keep, and phrase grouping metadata.
    """
    only = resolve_planner_clip_scope(clip_filenames, primary_source_file)
    scope = "selected" if only else "all"
    entries, _warnings = build_media_catalog(root, scope=scope, only_basenames=only)
    groups_out: list[dict[str, Any]] = []
    group_serial = 0

    for entry in entries:
        if (entry.get("analysis") or {}).get("merged_index") != "complete":
            continue
        kind = str(entry.get("kind") or "")
        if kind not in ("audio", "video"):
            continue
        name = str(entry.get("id") or "")
        if not name:
            continue
        takes = entry.get("takes")
        if not isinstance(takes, list) or not takes:
            continue
        phrase_groups = entry.get("phrase_groups")
        if not isinstance(phrase_groups, list):
            phrase_groups = []

        by_phrase: dict[int, list[dict]] = {}
        for t in takes:
            if not isinstance(t, dict):
                continue
            gi = int(t.get("phrase_group") if t.get("phrase_group") is not None else -1)
            by_phrase.setdefault(gi, []).append(t)

        for gi in sorted(by_phrase.keys()):
            attempts_raw = sorted(
                by_phrase[gi],
                key=lambda x: int(x.get("attempt_in_group") or 0),
            )
            phrase_label = ""
            for pg in phrase_groups:
                if isinstance(pg, dict) and int(pg.get("group_index", -1)) == gi:
                    phrase_label = str(pg.get("phrase_normalized") or pg.get("phrase") or "")
                    break
            if not phrase_label and attempts_raw:
                phrase_label = str(attempts_raw[-1].get("text") or "")[:120]

            attempt_count = len(attempts_raw)
            attempts: list[dict[str, Any]] = []
            for row in attempts_raw:
                ti = int(row.get("take_index", 0))
                ai = int(row.get("attempt_in_group") or 0)
                aid = take_attempt_id(name, ti)
                keep = default_keep_attempt(row, attempt_in_group=ai, attempt_count=attempt_count)
                attempts.append(
                    {
                        "id": aid,
                        "source_file": name,
                        "take_index": ti,
                        "phrase_group": gi,
                        "attempt_in_group": ai,
                        "start": row.get("start"),
                        "end": row.get("end"),
                        "text": row.get("text") or "",
                        "is_restart": bool(row.get("is_restart")),
                        "abandoned_sentence": bool(row.get("abandoned_sentence")),
                        "ends_complete_sentence": bool(row.get("ends_complete_sentence")),
                        "default_keep": keep,
                    }
                )

            if len(attempts) == 1 and not (
                attempts[0].get("abandoned_sentence") or attempts[0].get("is_restart")
            ):
                continue

            groups_out.append(
                {
                    "id": f"g{group_serial}",
                    "source_file": name,
                    "phrase_group": gi,
                    "phrase_label": phrase_label,
                    "attempts": attempts,
                }
            )
            group_serial += 1

    return groups_out


def excluded_time_ranges(
    root: Path,
    excluded_take_ids: list[str] | None,
) -> dict[str, list[tuple[float, float]]]:
    """Map footage basename → list of (start, end) seconds to exclude from planning."""
    if not excluded_take_ids:
        return {}
    wanted = {str(x).strip() for x in excluded_take_ids if str(x).strip()}
    if not wanted:
        return {}
    entries, _ = build_media_catalog(root, scope="all", only_basenames=None)
    out: dict[str, list[tuple[float, float]]] = {}
    for entry in entries:
        name = str(entry.get("id") or "")
        takes = entry.get("takes") if isinstance(entry.get("takes"), list) else []
        for row in takes:
            if not isinstance(row, dict):
                continue
            tid = take_attempt_id(name, int(row.get("take_index", 0)))
            if tid not in wanted:
                continue
            try:
                t0 = float(row["start"])
                t1 = float(row["end"])
            except (KeyError, TypeError, ValueError):
                continue
            out.setdefault(name, []).append((t0, t1))
    return out
