"""Extensions allowed under footage/ — shared by backend and scripts."""

from __future__ import annotations

# Video sources: proxy + thumbnail as today
VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".webm"})

# Standalone audio for timeline / waveform (no video stream)
AUDIO_EXTS: frozenset[str] = frozenset({".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus"})

# Everything the editor lists and can upload
FOOTAGE_EXTS: frozenset[str] = VIDEO_EXTS | AUDIO_EXTS
