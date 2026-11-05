#!/usr/bin/env python3
"""
Validate a timeline plan JSON before rendering.
Usage: python scripts/validate_plan.py plans/<plan>.json [--max-length SEC]
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from media import video_duration_seconds  # noqa: E402

MIN_SEGMENT_SECONDS = 0.3


def load_segments(plan_path: Path) -> list[dict]:
    data = json.loads(plan_path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "segments" in data:
        return data["segments"]
    raise ValueError("Plan must be a list or object with 'segments'")


def resolve_source(raw: str) -> Path:
    path = Path(raw)
    if not path.is_file():
        path = Path.cwd() / raw
    if not path.is_file():
        raise FileNotFoundError(raw)
    return path


def validate_segments(
    segments: list[dict],
    max_length: float | None = None,
) -> list[str]:
    errors: list[str] = []
    if not segments:
        errors.append("Plan has no segments.")
        return errors

    total_out = 0.0
    for i, seg in enumerate(segments):
        label = f"Segment {i}"
        if "source" not in seg or "start" not in seg or "end" not in seg:
            errors.append(f"{label}: missing source, start, or end.")
            continue
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (TypeError, ValueError):
            errors.append(f"{label}: start/end must be numbers.")
            continue

        if start >= end:
            errors.append(f"{label}: start ({start}) must be less than end ({end}).")

        length = end - start
        if length < MIN_SEGMENT_SECONDS:
            errors.append(
                f"{label}: length {length:.3f}s is under minimum {MIN_SEGMENT_SECONDS}s."
            )
        total_out += max(end - start, 0)

        try:
            source = resolve_source(seg["source"])
        except FileNotFoundError:
            errors.append(f"{label}: source file not found: {seg['source']}")
            continue

        try:
            duration = video_duration_seconds(source)
        except RuntimeError as e:
            errors.append(f"{label}: {e}")
            continue

        if end > duration + 0.02:
            errors.append(
                f"{label}: end {end:.3f}s exceeds source duration {duration:.3f}s "
                f"({source.name})."
            )

    if max_length is not None and total_out > max_length + 0.05:
        errors.append(
            f"Total output length {total_out:.2f}s exceeds max {max_length:.2f}s."
        )

    return errors


def validate_plan(
    plan_path: Path,
    max_length: float | None = None,
) -> list[str]:
    try:
        segments = load_segments(plan_path)
    except (json.JSONDecodeError, ValueError) as e:
        return [str(e)]
    return validate_segments(segments, max_length)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate timeline plan JSON")
    parser.add_argument("plan_path")
    parser.add_argument(
        "--max-length",
        type=float,
        default=None,
        help="Fail if total kept duration exceeds this many seconds",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan_path)
    if not plan_path.is_file():
        print(f"Error: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    errors = validate_plan(plan_path, args.max_length)
    if errors:
        print("Plan validation failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print(f"Plan OK: {plan_path}")


if __name__ == "__main__":
    main()
