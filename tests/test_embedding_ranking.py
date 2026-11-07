"""Compare hash vs sentence-transformer ranking (no token overlap with briefs)."""

from __future__ import annotations

import re

import pytest

from text_embeddings import build_embedding_payload, rank_entries_by_brief

COAST = {
    "id": "coast.mov",
    "transcript_segments": [],
    "ai_frame_captions": [
        {"description": "Swells roll toward craggy shoreline under amber twilight."},
        {"description": "Gulls circle above foaming breakers near a weathered pier."},
    ],
}

METRO = {
    "id": "metro.mov",
    "transcript_segments": [],
    "ai_frame_captions": [
        {"description": "Neon signs reflect on rain-slick pavement after midnight."},
        {"description": "Crowds pulse beneath strobing club lights downtown."},
    ],
}

KITCHEN = {
    "id": "kitchen.mov",
    "transcript_segments": [],
    "ai_frame_captions": [
        {"description": "Steam curls from a ceramic mug beside flaky pastry."},
        {"description": "Morning light grazes a wooden counter and brass kettle."},
    ],
}

ENTRIES = [COAST, METRO, KITCHEN]

# Briefs chosen so no [a-z0-9] token appears in the winning description text.
BRIEF_CASES: list[tuple[str, str]] = [
    ("ocean travel expedition", "coast.mov"),
    ("coastal vacation vibe", "coast.mov"),
    ("city nightlife energy", "metro.mov"),
    ("rainy metropolitan streets", "metro.mov"),
    ("espresso breakfast nook", "kitchen.mov"),
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _brief_has_no_token_overlap(brief: str, entry: dict) -> bool:
    bt = _tokens(brief)
    for frame in entry.get("ai_frame_captions") or []:
        desc = str(frame.get("description") or "")
        if bt & _tokens(desc):
            return False
    return True


@pytest.mark.parametrize("brief,expected_id", BRIEF_CASES)
def test_briefs_have_no_literal_token_overlap(brief: str, expected_id: str):
    winner = next(e for e in ENTRIES if e["id"] == expected_id)
    assert _brief_has_no_token_overlap(brief, winner)


def test_hash_ranking_on_no_overlap_briefs():
    for brief, expected_id in BRIEF_CASES:
        ranked = rank_entries_by_brief(brief, ENTRIES, method="hash", force=False)
        top = ranked[0][0]
        # Hash has no semantics; we only assert it returns scores in [−1, 1].
        assert ranked[0][1] <= 1.0
        assert ranked[0][1] >= -1.0
        # Document: hash may pick wrong file when tokens do not overlap.
        _ = (brief, expected_id, top)


def test_sentence_transformer_beats_hash_on_no_overlap():
    pytest.importorskip("sentence_transformers")
    wins_st = 0
    wins_hash = 0
    for brief, expected_id in BRIEF_CASES:
        st_ranked = rank_entries_by_brief(
            brief, ENTRIES, method="sentence_transformer", force=False
        )
        hash_ranked = rank_entries_by_brief(brief, ENTRIES, method="hash", force=False)
        if st_ranked[0][0] == expected_id:
            wins_st += 1
        if hash_ranked[0][0] == expected_id:
            wins_hash += 1
    assert wins_st >= 4
    assert wins_hash <= 2
