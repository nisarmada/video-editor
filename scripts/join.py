#!/usr/bin/env python3
"""
Join multiple clips into one vertical 1080x1920 @ 30fps video.
Usage: python scripts/join.py <output> <input1> <input2> [more inputs...]
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from media import join_files  # noqa: E402


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python scripts/join.py <output> <input1> <input2> [more...]",
            file=sys.stderr,
        )
        sys.exit(1)

    output_path = Path(sys.argv[1])
    input_paths = [Path(p) for p in sys.argv[2:]]

    for p in input_paths:
        if not p.is_file():
            print(f"Error: input file not found: {p}", file=sys.stderr)
            sys.exit(1)

    print("Running ffmpeg (re-encode; this can take a while)...")
    try:
        join_files(input_paths, output_path)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
