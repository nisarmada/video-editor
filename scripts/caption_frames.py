#!/usr/bin/env python3
"""
Describe keyframe images with Claude (one API request for all frames).
Usage: python scripts/caption_frames.py <video_path> [--force]
"""

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from index_cache import cache_hit, captions_path, keyframes_path, load_json, save_json  # noqa: E402

# Haiku is cheap and fast for vision; override with ANTHROPIC_CAPTION_MODEL in .env
DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # also try claude-haiku-5-5 when available

SYSTEM_PROMPT = """You caption video keyframes for an automated editor.
Return ONLY valid JSON (no markdown): an array with one object per frame, in the same order as the images.
Each object must have:
- shot_index (integer, matching the label before each image)
- time_seconds (number)
- description (what is happening in the shot, not a bare list of objects)
- shot_type (e.g. close-up, medium, wide, POV)
- main_subject (string)
- mood (string)
"""


def parse_json_response(text: str) -> list[dict]:
    """Extract JSON array from model output."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if isinstance(data, dict) and "frames" in data:
        data = data["frames"]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of frame captions")
    return data


def build_message_content(keyframes: list[dict]) -> list[dict]:
    """Anthropic message content: image + label pairs, then instructions."""
    blocks: list[dict] = []
    for kf in keyframes:
        rel = kf["path"]
        img_path = Path.cwd() / rel
        if not img_path.is_file():
            raise FileNotFoundError(f"Keyframe image not found: {img_path}")
        raw = base64.standard_b64encode(img_path.read_bytes()).decode("ascii")
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": raw,
                },
            }
        )
        blocks.append(
            {
                "type": "text",
                "text": (
                    f"Frame shot_index={kf.get('shot_index')} "
                    f"time_seconds={kf.get('time')}"
                ),
            }
        )
    blocks.append(
        {
            "type": "text",
            "text": (
                f"Caption all {len(keyframes)} frames above. "
                + SYSTEM_PROMPT
            ),
        }
    )
    return blocks


def caption_keyframes(keyframes: list[dict], model: str) -> list[dict]:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY not set. Add it to .env in the project root.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    content = build_message_content(keyframes)

    print(f"Calling Anthropic ({model}) with {len(keyframes)} frame(s)...")
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    parts = [block.text for block in response.content if block.type == "text"]
    if not parts:
        raise RuntimeError("Empty response from API")
    return parse_json_response("\n".join(parts))


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="AI captions for keyframe images")
    parser.add_argument("video_path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-call the API even if captions JSON exists",
    )
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_path = captions_path(video_path)
    if cache_hit(out_path, args.force):
        print(f"Using cached frame captions: {out_path}")
        data = load_json(out_path) or {}
        print(f"  {len(data.get('frames', []))} frame description(s)")
        return

    kf_doc = load_json(keyframes_path(video_path))
    if not kf_doc or not kf_doc.get("keyframes"):
        print(
            f"Error: run keyframes.py first ({keyframes_path(video_path)})",
            file=sys.stderr,
        )
        sys.exit(1)

    keyframes = kf_doc["keyframes"]
    print(f"Found {len(keyframes)} keyframe(s) to caption.")

    model = os.environ.get("ANTHROPIC_CAPTION_MODEL", DEFAULT_MODEL)
    try:
        frames = caption_keyframes(keyframes, model)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        err = str(e).lower()
        if "model" in err or "not_found" in err:
            print(
                "Tip: set ANTHROPIC_CAPTION_MODEL in .env to a current Haiku ID "
                "from https://docs.anthropic.com/en/docs/about-claude/models",
                file=sys.stderr,
            )
        sys.exit(1)

    payload = {
        "clip": video_path.name,
        "model": model,
        "frames": frames,
    }
    save_json(out_path, payload)
    print(f"Saved: {out_path}  ({len(frames)} descriptions)")


if __name__ == "__main__":
    main()
