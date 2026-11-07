#!/usr/bin/env python3
"""
Local text embeddings from transcript sentences and shot descriptions.
Used for catalog ranking against the brief. No paid API.

Methods (Settings → Embedding):
  hash — 48-d hashed bag-of-words per sentence (token → SHA256 bucket ±1, L2 norm).
         Fast, no extra deps; matching is mostly literal token overlap.
  sentence_transformer — local all-MiniLM-L6-v2 (sentence-transformers), cached on disk.
         Falls back to hash if the package/model is unavailable.

Usage: python scripts/text_embeddings.py <media_path> [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from embedding_settings import load_embedding_settings  # noqa: E402
from index_cache import (  # noqa: E402
    cache_hit,
    embedding_path,
    load_json,
    merged_index_path,
    save_json_atomic,
)

HASH_EMBED_DIM = 48
EMBED_VERSION = 3

_st_model_name: str | None = None
_st_model: Any = None


def hash_embed(text: str) -> list[float]:
    """Hashed bag-of-words: each [a-z0-9] token maps to one of 48 buckets (±1), then L2-normalize."""
    vec = [0.0] * HASH_EMBED_DIM
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % HASH_EMBED_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _split_segment_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?])\s+", clean)
    out = [p.strip() for p in parts if p.strip()]
    return out if out else [clean]


def sentences_from_merged(merged: dict) -> list[str]:
    sentences: list[str] = []
    tr = merged.get("transcript") if isinstance(merged.get("transcript"), dict) else {}
    for seg in tr.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text or text.lower() in {"no speech detected", "not analyzed"}:
            continue
        sentences.extend(_split_segment_sentences(text))

    caps = merged.get("captions") if isinstance(merged.get("captions"), dict) else {}
    for frame in caps.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        desc = str(frame.get("description") or frame.get("caption") or "").strip()
        if desc:
            sentences.extend(_split_segment_sentences(desc))

    seen: set[str] = set()
    unique: list[str] = []
    for s in sentences:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return unique


def sentences_from_catalog_entry(entry: dict) -> list[str]:
    merged_like = {
        "transcript": {"segments": entry.get("transcript_segments") or []},
        "captions": {"frames": entry.get("ai_frame_captions") or []},
    }
    return sentences_from_merged(merged_like)


def sentences_text_hash(sentences: list[str]) -> str:
    blob = "\n".join(sentences)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _get_sentence_transformer(model_name: str) -> Any:
    global _st_model, _st_model_name
    if _st_model is not None and _st_model_name == model_name:
        return _st_model
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    _st_model = SentenceTransformer(model_name)
    _st_model_name = model_name
    return _st_model


def sentence_transformer_embed(text: str, *, model_name: str) -> list[float]:
    model = _get_sentence_transformer(model_name)
    vec = model.encode(text or "", normalize_embeddings=True)
    return [float(x) for x in vec]


def embed_text(text: str, *, method: str, model_name: str) -> list[float]:
    if method == "sentence_transformer":
        try:
            return sentence_transformer_embed(text, model_name=model_name)
        except Exception:
            return hash_embed(text)
    return hash_embed(text)


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return hash_embed("")
    dim = len(vectors[0])
    mean = [0.0] * dim
    for vec in vectors:
        for i, v in enumerate(vec):
            mean[i] += v
    mean = [v / len(vectors) for v in mean]
    norm = math.sqrt(sum(v * v for v in mean))
    return [v / norm for v in mean] if norm > 0 else mean


def build_embedding_payload(
    sentences: list[str],
    *,
    method: str | None = None,
    model_name: str | None = None,
    force_method: bool = False,
) -> dict[str, Any]:
    settings = load_embedding_settings()
    use_method = method or str(settings.get("method") or "hash")
    use_model = model_name or str(settings.get("model_name") or "all-MiniLM-L6-v2")
    resolved_method = use_method
    if use_method == "sentence_transformer":
        try:
            sentence_vectors = [
                sentence_transformer_embed(s, model_name=use_model) for s in sentences
            ]
            vector = _mean_vector(sentence_vectors) if sentence_vectors else embed_text(
                "", method="sentence_transformer", model_name=use_model
            )
            dim = len(vector)
        except Exception:
            resolved_method = "hash"
            sentence_vectors = [hash_embed(s) for s in sentences]
            vector = _mean_vector(sentence_vectors)
            dim = HASH_EMBED_DIM
    else:
        sentence_vectors = [hash_embed(s) for s in sentences]
        vector = _mean_vector(sentence_vectors)
        dim = HASH_EMBED_DIM

    payload: dict[str, Any] = {
        "version": EMBED_VERSION,
        "method": resolved_method,
        "model_name": use_model if resolved_method == "sentence_transformer" else None,
        "embed_dim": dim,
        "text_hash": sentences_text_hash(sentences),
        "sentence_count": len(sentences),
        "sentences": sentences,
        "sentence_vectors": sentence_vectors,
        "vector": vector,
    }
    if force_method:
        payload["requested_method"] = use_method
    return payload


def score_brief_against_payload(brief: str, payload: dict) -> float:
    method = str(payload.get("method") or "hash")
    model_name = str(payload.get("model_name") or "all-MiniLM-L6-v2")
    brief_vec = embed_text(brief or "", method=method, model_name=model_name)
    vectors = payload.get("sentence_vectors")
    if isinstance(vectors, list) and vectors:
        best = 0.0
        for vec in vectors:
            if not vec:
                continue
            row = [float(x) for x in vec]
            if len(row) != len(brief_vec):
                continue
            best = max(best, cosine(brief_vec, row))
        return best
    vector = payload.get("vector")
    if isinstance(vector, list):
        row = [float(x) for x in vector]
        if len(row) == len(brief_vec):
            return cosine(brief_vec, row)
    return 0.0


def _cache_matches(cached: dict, text_hash: str, settings: dict) -> bool:
    if cached.get("version") != EMBED_VERSION:
        return False
    if cached.get("text_hash") != text_hash:
        return False
    want_method = str(settings.get("method") or "hash")
    if cached.get("method") != want_method:
        return False
    if want_method == "sentence_transformer":
        want_model = str(settings.get("model_name") or "all-MiniLM-L6-v2")
        if cached.get("model_name") != want_model:
            return False
    return isinstance(cached.get("sentence_vectors"), list)


def ensure_file_embedding(
    file_id: str,
    *,
    sentences: list[str],
    force: bool = False,
) -> dict[str, Any]:
    settings = load_embedding_settings()
    path = embedding_path(Path(file_id))
    text_hash = sentences_text_hash(sentences)
    if not force:
        cached = load_json(path)
        if isinstance(cached, dict) and _cache_matches(cached, text_hash, settings):
            return cached
    payload = build_embedding_payload(sentences)
    save_json_atomic(path, payload)
    return payload


def relevance_for_entry(brief: str, entry: dict, *, force: bool = False) -> float:
    sentences = sentences_from_catalog_entry(entry)
    file_id = str(entry.get("id") or "file")
    payload = ensure_file_embedding(file_id, sentences=sentences, force=force)
    return score_brief_against_payload(brief, payload)


def rank_entries_by_brief(
    brief: str,
    entries: list[dict],
    *,
    method: str,
    model_name: str = "all-MiniLM-L6-v2",
    force: bool = True,
) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for entry in entries:
        fid = str(entry.get("id") or "file")
        sentences = sentences_from_catalog_entry(entry)
        payload = build_embedding_payload(
            sentences,
            method=method,
            model_name=model_name,
        )
        if force:
            save_json_atomic(embedding_path(Path(fid)), payload)
        score = score_brief_against_payload(brief, payload)
        scored.append((fid, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def build_file_embedding(media_path: Path, *, force: bool = False) -> dict[str, Any]:
    media_path = media_path.resolve()
    out_path = embedding_path(media_path)
    merged = load_json(merged_index_path(media_path))
    if not isinstance(merged, dict):
        merged = {}
    sentences = sentences_from_merged(merged)
    settings = load_embedding_settings()
    text_hash = sentences_text_hash(sentences)

    if cache_hit(out_path, force) and not force:
        cached = load_json(out_path)
        if isinstance(cached, dict) and _cache_matches(cached, text_hash, settings):
            return cached

    t0 = time.perf_counter()
    payload = build_embedding_payload(sentences)
    payload["clip"] = media_path.name
    payload["timing_ms"] = {"total": int((time.perf_counter() - t0) * 1000)}
    save_json_atomic(out_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local text embedding cache")
    parser.add_argument("media_path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    path = Path(args.media_path)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    out_path = embedding_path(path)
    settings = load_embedding_settings()
    if cache_hit(out_path, args.force) and not args.force:
        data = load_json(out_path)
        if isinstance(data, dict) and _cache_matches(
            data,
            sentences_text_hash(sentences_from_merged(load_json(merged_index_path(path)) or {})),
            settings,
        ):
            print(f"Using cached embedding: {out_path}")
            return

    payload = build_file_embedding(path, force=args.force)
    print(
        f"Saved: {out_path}  method={payload.get('method')}  "
        f"sentences={payload.get('sentence_count')}  dim={payload.get('embed_dim')}"
    )


if __name__ == "__main__":
    main()
