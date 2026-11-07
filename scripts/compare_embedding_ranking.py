#!/usr/bin/env python3
"""Print hash vs sentence-transformer rankings for fixed no-overlap briefs."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from text_embeddings import rank_entries_by_brief  # noqa: E402

ENTRIES = [
    {
        "id": "coast.mov",
        "ai_frame_captions": [
            {"description": "Swells roll toward craggy shoreline under amber twilight."},
            {"description": "Gulls circle above foaming breakers near a weathered pier."},
        ],
    },
    {
        "id": "metro.mov",
        "ai_frame_captions": [
            {"description": "Neon signs reflect on rain-slick pavement after midnight."},
            {"description": "Crowds pulse beneath strobing club lights downtown."},
        ],
    },
    {
        "id": "kitchen.mov",
        "ai_frame_captions": [
            {"description": "Steam curls from a ceramic mug beside flaky pastry."},
            {"description": "Morning light grazes a wooden counter and brass kettle."},
        ],
    },
]

BRIEF_CASES = [
    ("ocean travel expedition", "coast.mov"),
    ("coastal vacation vibe", "coast.mov"),
    ("city nightlife energy", "metro.mov"),
    ("rainy metropolitan streets", "metro.mov"),
    ("espresso breakfast nook", "kitchen.mov"),
]


def main() -> None:
    print("Brief | expected | hash top | hash score | ST top | ST score")
    print("-" * 72)
    for brief, expected_id in BRIEF_CASES:
        h = rank_entries_by_brief(brief, ENTRIES, method="hash", force=False)
        try:
            s = rank_entries_by_brief(
                brief, ENTRIES, method="sentence_transformer", force=False
            )
        except Exception as e:  # noqa: BLE001
            print(f"{brief!r}: ST unavailable ({e})")
            continue
        print(
            f"{brief!r} | {expected_id} | {h[0][0]} | {h[0][1]:.4f} | "
            f"{s[0][0]} | {s[0][1]:.4f} | "
            f"hash_ok={h[0][0]==expected_id} st_ok={s[0][0]==expected_id}"
        )


if __name__ == "__main__":
    main()
