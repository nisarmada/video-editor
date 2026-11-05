#!/usr/bin/env python3
"""
Convert a v1 timeline plan to schema v2 (multi-track).
Usage: python scripts/convert_v1_to_v2.py plans/old.json plans/new_v2.json
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from timeline_format import SCHEMA_V2, v1_segments_from_data  # noqa: E402


def segment_duration(seg: dict) -> float:
    return float(seg["end"]) - float(seg["start"])


def convert(
    data: dict | list,
    *,
    created_by: str | None = None,
    group_id: str | None = None,
) -> dict:
    """
    Build a v2 timeline from v1 segments.

    If created_by is set, every clip uses it (otherwise ai when segment has
    reason, else user). If group_id is set, every clip gets that group unless
    the segment already has group_id.
    """
    segments = v1_segments_from_data(data)
    meta = data if isinstance(data, dict) else {}

    timeline_cursor = 0.0
    video_clips: list[dict] = []
    caption_clips: list[dict] = []

    for seg in segments:
        dur = segment_duration(seg)
        if created_by is not None:
            created = created_by
        else:
            created = "ai" if seg.get("reason") else "user"
        group = seg.get("group_id") if seg.get("group_id") else group_id
        clip_id = str(uuid.uuid4())

        video_clips.append(
            {
                "id": clip_id,
                "source": seg["source"],
                "source_in": float(seg["start"]),
                "source_out": float(seg["end"]),
                "timeline_start": round(timeline_cursor, 3),
                "created_by": created,
                **({"group_id": group} if group else {}),
                **({"zoom": seg["zoom"]} if seg.get("zoom") is not None else {}),
                **({"speed": seg["speed"]} if seg.get("speed") is not None else {}),
                **({"volume": seg["volume"]} if seg.get("volume") is not None else {}),
                **({"caption": seg["caption"]} if seg.get("caption") else {}),
            }
        )

        text = seg.get("caption") or seg.get("text")
        if text:
            cap_id = str(uuid.uuid4())
            caption_clips.append(
                {
                    "id": cap_id,
                    "source": seg["source"],
                    "source_in": float(seg["start"]),
                    "source_out": float(seg["end"]),
                    "timeline_start": round(timeline_cursor, 3),
                    "text": text,
                    "created_by": created,
                    **({"group_id": group} if group else {}),
                }
            )

        speed = float(seg.get("speed") or 1.0)
        timeline_cursor += dur / speed if speed > 0 else dur

    out: dict = {
        "schema_version": SCHEMA_V2,
        "tracks": [
            {
                "id": "track-video-main",
                "type": "video",
                "label": "Video",
                "clips": video_clips,
            },
            {
                "id": "track-audio-main",
                "type": "audio",
                "label": "Audio",
                "clips": [],
            },
            {
                "id": "track-caption-main",
                "type": "caption",
                "label": "Captions",
                "clips": caption_clips,
            },
        ],
    }

    for key in ("name", "brief", "target_length_seconds"):
        if key in meta:
            out[key] = meta[key]

    settings = meta.get("settings")
    if settings:
        out["settings"] = settings
    else:
        out["settings"] = {"width": 1080, "height": 1920, "fps": 30}

    if "target_length_seconds" not in out:
        out["target_length_seconds"] = round(timeline_cursor, 3)

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert v1 plan JSON to timeline v2")
    parser.add_argument("input_plan")
    parser.add_argument("output_plan")
    args = parser.parse_args()

    in_path = Path(args.input_plan)
    if not in_path.is_file():
        print(f"Error: not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(in_path.read_text())
    if isinstance(data, dict) and data.get("schema_version") == SCHEMA_V2:
        print("Input is already schema v2; copying structure.", file=sys.stderr)

    v2 = convert(data)
    out_path = Path(args.output_plan)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(v2, indent=2, ensure_ascii=False) + "\n")
    n = len(v2["tracks"][0]["clips"])
    print(f"Wrote v2 plan: {out_path}  ({n} video clip(s))")


if __name__ == "__main__":
    main()
