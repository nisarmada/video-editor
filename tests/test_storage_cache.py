"""Regenerable cache disk stats and cleanup."""

from __future__ import annotations

from pathlib import Path

from backend.storage_cache import (
    clear_paid_caption_caches,
    clear_regenerable_caches,
    storage_stats,
)


def test_clear_removes_embed_and_image_dirs(tmp_path: Path):
    index = tmp_path / "index"
    perception = index / "perception" / "clip"
    perception.mkdir(parents=True)
    (perception / "shot0.jpg").write_bytes(b"x" * 100)
    (index / "demo_embed.json").write_text("{}", encoding="utf-8")
    (tmp_path / "footage").mkdir()
    (tmp_path / "footage" / "keep.mov").write_bytes(b"video")

    before = storage_stats(tmp_path)
    assert before["perception_images_bytes"] >= 100

    result = clear_regenerable_caches(tmp_path)
    assert result["freed_bytes"] >= 100
    assert not (index / "demo_embed.json").is_file()
    assert not perception.is_dir()
    assert (tmp_path / "footage" / "keep.mov").is_file()


def test_regenerable_clear_keeps_captions(tmp_path: Path):
    index = tmp_path / "index"
    index.mkdir(parents=True)
    cap = index / "clip_captions.json"
    cap.write_text("{}", encoding="utf-8")
    (index / "clip_embed.json").write_text("{}", encoding="utf-8")

    clear_regenerable_caches(tmp_path)
    assert cap.is_file()
    assert not (index / "clip_embed.json").is_file()


def test_clear_paid_captions_only(tmp_path: Path):
    index = tmp_path / "index"
    index.mkdir(parents=True)
    cap = index / "clip_captions.json"
    cap.write_bytes(b"x" * 50)
    (index / "clip_embed.json").write_text("{}", encoding="utf-8")

    result = clear_paid_caption_caches(tmp_path)
    assert not cap.is_file()
    assert (index / "clip_embed.json").is_file()
    assert result["removed_files"] == 1
