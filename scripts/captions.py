#!/usr/bin/env python3
"""
Build word-by-word ASS subtitles for a timeline plan (remapped to edited time).
Usage: python scripts/captions.py <plan.json> [-o output.ass]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import load_json, transcript_path  # noqa: E402
from caption_style_resolve import (  # noqa: E402
    default_caption_style,
    merge_style_dict,
    resolve_merged_style_for_plan,
    style_for_segment,
)
from timeline_format import (  # noqa: E402
    TIMELINE_GAP_SOURCE,
    load_plan_file,
    v1_segments_from_data,
)

# Legacy constants (PNG fallback in media.py)
PLAY_RES_X = 1080
PLAY_RES_Y = 1920
FONT_NAME = "Arial"
FONT_SIZE = 72
FONT_BOLD = True
PRIMARY_COLOUR = "&H00FFFFFF"
HIGHLIGHT_COLOUR = "&H0000FFFF"
OUTLINE_COLOUR = "&H00000000"
BACK_COLOUR = "&H80000000"
MARGIN_V = 280
WORDS_PER_LINE = 3

from captions_ass import build_ass_from_events  # noqa: E402


def load_segments(plan_path: Path) -> list[dict]:
    data = load_plan_file(plan_path)
    return v1_segments_from_data(data)


def load_plan_data(plan_path: Path) -> dict | list:
    return load_plan_file(plan_path)


def source_stem(source: str) -> str:
    return Path(source).stem


def words_for_clip(stem: str) -> list[dict]:
    path = Path.cwd() / "index" / f"{stem}_transcript.json"
    if not path.is_file():
        path = transcript_path(Path(stem + ".mp4"))
    doc = load_json(path)
    if not doc:
        return []
    words: list[dict] = []
    for seg in doc.get("segments") or []:
        words.extend(seg.get("words") or [])
    words.sort(key=lambda w: float(w["start"]))
    return words


def word_in_segment(ws: float, we: float, seg_start: float, seg_end: float) -> bool:
    """True if any part of the word falls inside the kept segment."""
    return ws < seg_end - 0.001 and we > seg_start + 0.001


def remap_words(
    plan_segments: list[dict],
    plan_data: dict | list | None = None,
) -> list[dict]:
    """Map transcript words onto the edited timeline; attach `_style` per word."""
    merged = (
        resolve_merged_style_for_plan(plan_data)
        if isinstance(plan_data, dict)
        else default_caption_style()
    )
    remapped: list[dict] = []
    output_cursor = 0.0
    seen_source_words: set[tuple[str, float, float]] = set()

    for seg in plan_segments:
        src = seg["source"]
        st = style_for_segment(merged, seg)
        if src == TIMELINE_GAP_SOURCE:
            seg_len = float(seg["end"]) - float(seg["start"])
            output_cursor += seg_len
            continue
        stem = source_stem(src)
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        seg_len = seg_end - seg_start

        for w in words_for_clip(stem):
            ws = float(w["start"])
            we = float(w["end"])
            if not word_in_segment(ws, we, seg_start, seg_end):
                continue

            dedupe_key = (stem, round(ws, 3), round(we, 3))
            if dedupe_key in seen_source_words:
                continue
            seen_source_words.add(dedupe_key)

            clip_start = max(ws, seg_start)
            clip_end = min(we, seg_end)
            if clip_end - clip_start < 0.03:
                continue

            remapped.append(
                {
                    "word": w.get("word", "").strip(),
                    "start": round(output_cursor + (clip_start - seg_start), 3),
                    "end": round(output_cursor + (clip_end - seg_start), 3),
                    "_style": st,
                    "_clip_id": seg.get("_clip_id"),
                }
            )
        output_cursor += seg_len

    remapped.sort(key=lambda x: (x["start"], x["end"]))
    return remapped


def ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def chunk_words(words: list[dict], size: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    for i in range(0, len(words), size):
        chunks.append(words[i : i + size])
    return chunks


def visible_words(chunk: list[dict], active: dict) -> list[dict]:
    try:
        idx = chunk.index(active)
    except ValueError:
        return [active]
    return chunk[: idx + 1]


def caption_events(
    words: list[dict],
    plan_data: dict | list | None = None,
    max_words_per_line: int | None = None,
) -> list[dict]:
    """
    Timed events for ASS burn-in. Each event includes chunk, active, and merged style.
    """
    default_st = (
        resolve_merged_style_for_plan(plan_data)
        if isinstance(plan_data, dict)
        else default_caption_style()
    )
    line_size = max_words_per_line or int(default_st.get("max_words_per_line", 3))
    line_size = max(1, min(5, line_size))

    events: list[dict] = []
    if not words:
        return events

    if not any("_style" in w for w in words):
        for chunk in chunk_words(words, line_size):
            chunk_style = default_st
            for active in chunk:
                t_start = float(active["start"])
                t_end = float(active["end"])
                if t_end <= t_start:
                    t_end = t_start + 0.05
                events.append(
                    {
                        "start": t_start,
                        "end": t_end,
                        "chunk": visible_words(chunk, active),
                        "active": active,
                        "style": chunk_style,
                    }
                )
        return events

    i = 0
    n = len(words)
    while i < n:
        row_style = words[i].get("_style", default_st)
        if not isinstance(row_style, dict):
            row_style = default_st
        line_size = int(row_style.get("max_words_per_line", line_size))
        line_size = max(1, min(5, line_size))
        chunk = words[i : i + line_size]
        i += line_size
        for active in chunk:
            t_start = float(active["start"])
            t_end = float(active["end"])
            if t_end <= t_start:
                t_end = t_start + 0.05
            ev_style = active.get("_style", row_style)
            events.append(
                {
                    "start": t_start,
                    "end": t_end,
                    "chunk": visible_words(chunk, active),
                    "active": active,
                    "style": ev_style,
                }
            )
    return events


def sample_preview_ass(
    style: dict[str, Any] | None,
    video_w: int = PLAY_RES_X,
    video_h: int = PLAY_RES_Y,
) -> str:
    """Fixed phrase for preset grid mini-previews (same ASS pipeline as export)."""
    merged = merge_style_dict(default_caption_style(), style) if style else default_caption_style()
    words = [
        {"word": "Bold", "start": 0.0, "end": 0.85, "_style": merged},
        {"word": "captions", "start": 1.0, "end": 1.85, "_style": merged},
        {"word": "pop", "start": 2.0, "end": 2.85, "_style": merged},
    ]
    plan_stub: dict[str, Any] = {
        "schema_version": 2,
        "settings": {
            "width": video_w,
            "height": video_h,
            "caption_style": style or {},
        },
        "tracks": [],
    }
    evs = caption_events(words, plan_data=plan_stub)
    return build_ass_from_events(evs, merged, video_w, video_h)


def build_ass_for_timeline(
    plan_data: dict,
    *,
    style: dict[str, Any] | None = None,
    clip_ids: list[str] | None = None,
    style_target: str = "plan",
    style_clip_id: str | None = None,
    video_w: int = PLAY_RES_X,
    video_h: int = PLAY_RES_Y,
) -> str:
    """
    Same ASS as export: merge optional style into settings.caption_style,
    or into one video clip's style_override; optionally filter words by clip id(s).
    """
    tl = copy.deepcopy(plan_data)
    if style:
        if style_target == "clip" and style_clip_id:
            for track in tl.get("tracks") or []:
                if track.get("type") != "video":
                    continue
                for c in track.get("clips") or []:
                    if c.get("id") == style_clip_id:
                        prev = c.get("style_override")
                        base = prev if isinstance(prev, dict) else {}
                        c["style_override"] = merge_style_dict(base, style)
                        break
        else:
            if not isinstance(tl.get("settings"), dict):
                tl["settings"] = {}
            cs = tl["settings"].setdefault("caption_style", {})
            if not isinstance(cs, dict):
                tl["settings"]["caption_style"] = {}
                cs = tl["settings"]["caption_style"]
            for k, v in style.items():
                if v is not None:
                    cs[k] = v
    segs = v1_segments_from_data(tl)
    words = remap_words(segs, plan_data=tl)
    if clip_ids:
        allow = set(clip_ids)
        words = [w for w in words if w.get("_clip_id") in allow]
    merged = resolve_merged_style_for_plan(tl)
    evs = caption_events(words, plan_data=tl)
    return build_ass_from_events(evs, merged, video_w, video_h)


def build_ass(
    words: list[dict],
    plan_data: dict | list | None = None,
    video_w: int = PLAY_RES_X,
    video_h: int = PLAY_RES_Y,
) -> str:
    """Full ASS document; delegates to backend/captions_ass (same as API preview)."""
    merged = (
        resolve_merged_style_for_plan(plan_data)
        if isinstance(plan_data, dict)
        else default_caption_style()
    )
    evs = caption_events(words, plan_data=plan_data)
    return build_ass_from_events(evs, merged, video_w, video_h)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ASS captions for a plan")
    parser.add_argument("plan_path")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .ass path (default: next to plan with _captions.ass)",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan_path)
    if not plan_path.is_file():
        print(f"Error: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    out_path = args.output or plan_path.with_name(plan_path.stem + "_captions.ass")

    try:
        plan_data = load_plan_file(plan_path)
        segments = v1_segments_from_data(plan_data)
        words = remap_words(segments, plan_data=plan_data)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not words:
        print("Warning: no words mapped to this plan; writing empty ASS.", file=sys.stderr)

    tw = th = None
    if isinstance(plan_data, dict) and isinstance(plan_data.get("settings"), dict):
        s = plan_data["settings"]
        tw = s.get("width")
        th = s.get("height")
    w = int(tw) if isinstance(tw, (int, float)) else PLAY_RES_X
    h = int(th) if isinstance(th, (int, float)) else PLAY_RES_Y

    ass_text = build_ass(words, plan_data=plan_data, video_w=w, video_h=h)
    out_path.write_text(ass_text, encoding="utf-8")
    print(f"Wrote {len(words)} words -> {out_path}")


if __name__ == "__main__":
    main()
