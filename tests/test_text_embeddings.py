"""Sentence-level local embeddings for catalog ranking."""

from __future__ import annotations

from text_embeddings import (
    build_embedding_payload,
    hash_embed,
    relevance_for_entry,
    score_brief_against_payload,
    sentences_from_catalog_entry,
)


def test_ocean_brief_scores_ocean_file_higher():
    ocean = {
        "id": "ocean.mp4",
        "transcript_segments": [
            {"text": "Waves crash on the rocky shore at sunset."},
            {"text": "The ocean smells like salt and adventure."},
        ],
        "ai_frame_captions": [{"description": "Wide shot of blue ocean horizon."}],
    }
    city = {
        "id": "city.mp4",
        "transcript_segments": [
            {"text": "Traffic hums under neon billboards downtown."},
        ],
        "ai_frame_captions": [{"description": "Night street with taxis and crowds."}],
    }
    brief = "ocean travel reel with waves and salt air"
    ocean_score = relevance_for_entry(brief, ocean, force=True)
    city_score = relevance_for_entry(brief, city, force=True)
    assert ocean_score > city_score


def test_payload_sentence_count():
    sentences = sentences_from_catalog_entry(
        {
            "transcript_segments": [
                {"text": "Hello world. Second line."},
            ],
            "ai_frame_captions": [{"description": "A face on camera."}],
        }
    )
    payload = build_embedding_payload(sentences, method="hash")
    assert payload["sentence_count"] >= 2
    assert len(payload["sentence_vectors"]) == payload["sentence_count"]
    assert len(payload["vector"]) == len(hash_embed("x"))


def test_score_uses_best_sentence():
    payload = build_embedding_payload(
        ["unrelated kitchen appliances", "sunset beach waves crashing"],
        method="hash",
    )
    brief_score = score_brief_against_payload("beach sunset waves", payload)
    mean_only = score_brief_against_payload(
        "beach sunset waves",
        {"vector": payload["vector"], "sentence_vectors": []},
    )
    assert brief_score >= mean_only
