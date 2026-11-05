#!/usr/bin/env python3
"""
Build word-by-word ASS subtitles for a timeline plan (remapped to edited time).
Usage: python scripts/captions.py <plan.json> [-o output.ass]
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import load_json, transcript_path  # noqa: E402

# --- Easy to edit caption look (1080x1920 vertical) ---
PLAY_RES_X = 1080
PLAY_RES_Y = 1920
FONT_NAME = "Arial"
FONT_SIZE = 72
FONT_BOLD = True
PRIMARY_COLOUR = "&H00FFFFFF"  # white (ASS BGR)
HIGHLIGHT_COLOUR = "&H0000FFFF"  # yellow
OUTLINE_COLOUR = "&H00000000"
BACK_COLOUR = "&H80000000"
MARGIN_V = 280
WORDS_PER_LINE = 3


def load_segments(plan_path: Path) -> list[dict]:
    data = json.loads(plan_path.read_text())
    if isinstance(data, dict) and "segments" in data:
        return data["segments"]
    if isinstance(data, list):
        return data
    raise ValueError("Plan must contain segments")


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


def remap_words(plan_segments: list[dict]) -> list[dict]:
    """Map transcript words onto the edited timeline."""
    remapped: list[dict] = []
    output_cursor = 0.0

    for seg in plan_segments:
        src = seg["source"]
        stem = source_stem(src)
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        seg_len = seg_end - seg_start

        for w in words_for_clip(stem):
            ws = float(w["start"])
            we = float(w["end"])
            mid = (ws + we) / 2
            if mid < seg_start or mid > seg_end:
                continue
            remapped.append(
                {
                    "word": w.get("word", "").strip(),
                    "start": round(output_cursor + (ws - seg_start), 3),
                    "end": round(output_cursor + (we - seg_start), 3),
                }
            )
        output_cursor += seg_len

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


def caption_events(words: list[dict]) -> list[dict]:
    """Timed caption events for ASS or PNG overlay rendering."""
    events: list[dict] = []
    for chunk in chunk_words(words, WORDS_PER_LINE):
        for active in chunk:
            t_start = float(active["start"])
            t_end = float(active["end"])
            if t_end <= t_start:
                t_end = t_start + 0.05
            events.append(
                {
                    "start": t_start,
                    "end": t_end,
                    "chunk": chunk,
                    "active": active,
                }
            )
    return events


def build_ass(words: list[dict]) -> str:
    bold = -1 if FONT_BOLD else 0
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_RES_X}
PlayResY: {PLAY_RES_Y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOUR},{HIGHLIGHT_COLOUR},{OUTLINE_COLOUR},{BACK_COLOUR},{bold},0,0,0,100,100,0,0,1,3,0,2,40,40,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for event in caption_events(words):
        parts = []
        for w in event["chunk"]:
            text = escape_ass(w["word"])
            if w is event["active"]:
                parts.append(f"{{\\c{HIGHLIGHT_COLOUR}&}}{text}{{\\c{PRIMARY_COLOUR}&}}")
            else:
                parts.append(text)
        dialogue = " ".join(parts)
        lines.append(
            f"Dialogue: 0,{ass_time(event['start'])},{ass_time(event['end'])},Default,,0,0,0,,{dialogue}\n"
        )
    return "".join(lines)


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
        segments = load_segments(plan_path)
        words = remap_words(segments)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not words:
        print("Warning: no words mapped to this plan; writing empty ASS.", file=sys.stderr)

    ass_text = build_ass(words)
    out_path.write_text(ass_text, encoding="utf-8")
    print(f"Wrote {len(words)} words -> {out_path}")


if __name__ == "__main__":
    main()
