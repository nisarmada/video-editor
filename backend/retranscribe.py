"""Drop transcript-derived caches and re-queue the analysis pipeline."""

from __future__ import annotations

import sys
from pathlib import Path


def clear_transcript_dependent_index(root: Path, clip_path: Path) -> list[str]:
    """Remove cached JSON that transcription and downstream stages rebuild."""
    scripts = root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    from index_cache import (  # noqa: PLC0415
        audio_perception_path,
        embedding_path,
        merged_index_path,
        silences_path,
        takes_path,
        transcript_path,
    )

    removed: list[str] = []
    for path in (
        transcript_path(clip_path),
        silences_path(clip_path),
        audio_perception_path(clip_path),
        takes_path(clip_path),
        embedding_path(clip_path),
        merged_index_path(clip_path),
    ):
        if path.is_file():
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:
                pass
    return removed
