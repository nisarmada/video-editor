#!/usr/bin/env python3
"""
Build 540p proxy MP4s and thumbnails for footage/ (cached in index/proxies, index/thumbnails).
Usage: python scripts/make_proxies.py [--force] [footage/clip.mp4 ...]
"""

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from proxy_media import ensure_proxy, ensure_thumbnail, list_footage_files  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Create 540p proxies for footage clips")
    parser.add_argument(
        "clips",
        nargs="*",
        help="Specific footage files (default: all in footage/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when cache looks fresh",
    )
    args = parser.parse_args()

    root = Path.cwd()
    if args.clips:
        paths = []
        for raw in args.clips:
            p = Path(raw)
            if not p.is_file():
                p = root / raw
            if not p.is_file():
                print(f"Error: not found: {raw}", file=sys.stderr)
                sys.exit(1)
            paths.append(p)
    else:
        paths = list_footage_files(root)
        if not paths:
            print("No video files in footage/.")
            return

    for clip in paths:
        print(f"Proxy: {clip.name}")
        try:
            proxy = ensure_proxy(root, clip, force=args.force)
            thumb = ensure_thumbnail(root, clip, force=args.force)
            print(f"  -> {proxy.relative_to(root)}")
            print(f"  -> {thumb.relative_to(root)}")
        except RuntimeError as e:
            print(f"  Error: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Done ({len(paths)} clip(s)).")


if __name__ == "__main__":
    main()
