"""Proxy cache helpers (no FFmpeg)."""

from __future__ import annotations

from pathlib import Path

from proxy_media import footage_entry, proxy_path_for_clip, proxy_is_fresh


def test_footage_entry_lists_urls(tmp_path: Path):
    footage = tmp_path / "footage"
    footage.mkdir()
    clip = footage / "demo.mp4"
    clip.write_bytes(b"\x00")

    entry = footage_entry(tmp_path, clip)
    assert entry["name"] == "demo.mp4"
    assert entry["source"] == "footage/demo.mp4"
    assert entry["has_proxy"] is False
    assert entry["process_status"] == "pending"
    assert "/api/footage/demo.mp4/proxy" in entry["proxy_url"]


def test_proxy_is_fresh_when_newer(tmp_path: Path):
    clip = tmp_path / "a.mp4"
    clip.write_text("x")
    proxy = proxy_path_for_clip(tmp_path, clip)
    proxy.write_text("y")
    assert proxy_is_fresh(clip, proxy) is True
