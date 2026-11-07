#!/usr/bin/env python3
"""
Decode an exported mix and measure speech cut quality at timeline boundaries.
"""

from __future__ import annotations

import math
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from speech_cut_audit import (  # noqa: E402
    MAX_CLICK_SCORE,
    MIN_DECAY_RETAINED_MS,
    audit_timeline_speech_cuts,
    enumerate_speech_boundaries,
    merge_export_metrics,
)

WINDOW_S = 0.02
AUDITION_HALF_S = 0.5


def decode_audio_pcm(path: Path) -> tuple[list[float], int]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    raw = proc.stdout
    if len(raw) < 2:
        return [], 44100
    samples = [s / 32768.0 for s in struct.unpack(f"<{len(raw)//2}h", raw)]
    return samples, 44100


def _rms(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals))


def _slice(samples: list[float], sr: int, t0: float, t1: float) -> list[float]:
    i0 = max(0, int(t0 * sr))
    i1 = min(len(samples), int(t1 * sr))
    return samples[i0:i1]


def measure_at_timeline(
    samples: list[float],
    sr: int,
    timeline_time: float,
    *,
    next_timeline_start: float | None,
) -> dict[str, Any]:
    """Metrics in exported audio around a cut (timeline seconds)."""
    t = timeline_time
    before = _slice(samples, sr, t - 0.08, t)
    at = _slice(samples, sr, t - 0.005, t + 0.005)
    after = _slice(samples, sr, t, t + 0.12)
    peak = _rms(_slice(samples, sr, t - 0.35, t + 0.05)) or 1e-9
    rms_at = _rms(at)
    rms_before = _rms(before) or 1e-9
    energy_db = 20.0 * math.log10(max(rms_at, 1e-12) / peak)
    click = abs(rms_at - rms_before) / peak
    # decay retained: how long energy stays above noise floor after cut
    tail = _slice(samples, sr, t - 0.15, t)
    decay_ms = 0.0
    if tail:
        ref = _rms(tail) * 0.35
        for i in range(len(tail) - 1, -1, -1):
            if abs(tail[i]) > ref:
                decay_ms = (len(tail) - i) / sr * 1000.0
                break
    gap_ms = None
    if next_timeline_start is not None and next_timeline_start > t + 0.001:
        gap_region = _slice(samples, sr, t, next_timeline_start)
        if gap_region:
            silent_thresh = peak * 0.08
            run = 0
            for v in gap_region:
                if abs(v) < silent_thresh:
                    run += 1
                else:
                    run = 0
            gap_ms = run / sr * 1000.0
    problems: list[str] = []
    if decay_ms < MIN_DECAY_RETAINED_MS and _rms(before) > peak * 0.15:
        problems.append("may_clip_ending")
    if click > MAX_CLICK_SCORE:
        problems.append("high_click")
    return {
        "metrics": {
            "exported_decay_retained_ms": round(decay_ms, 1),
            "exported_energy_db": round(energy_db, 2),
            "exported_click_score": round(click, 4),
            "exported_gap_ms": round(gap_ms, 1) if gap_ms is not None else None,
        },
        "problems": problems,
    }


def verify_export_file(
    timeline: dict,
    export_path: Path,
) -> dict[str, Any]:
    samples, sr = decode_audio_pcm(export_path)
    boundaries = enumerate_speech_boundaries(timeline)
    export_rows: list[dict[str, Any]] = []
    for i, b in enumerate(boundaries):
        if b.edge != "out":
            continue
        nxt_t = None
        for j in range(i + 1, len(boundaries)):
            if boundaries[j].edge == "in" and boundaries[j].timeline_time >= b.timeline_time - 0.001:
                nxt_t = boundaries[j].timeline_time
                break
        m = measure_at_timeline(
            samples, sr, b.timeline_time, next_timeline_start=nxt_t
        )
        export_rows.append(
            {
                "clip_id": b.clip_id,
                "edge": b.edge,
                "metrics": m["metrics"],
                "problems": m["problems"],
            }
        )
    audit = audit_timeline_speech_cuts(timeline)
    return merge_export_metrics(audit, export_rows)


def validate_export_report(report: dict[str, Any]) -> list[str]:
    """Hard failures for tests."""
    errs: list[str] = []
    for b in report.get("boundaries") or []:
        if b.get("edge") != "out":
            continue
        if b.get("problems"):
            errs.append(f"{b.get('clip_id')} out: {','.join(b['problems'])}")
    return errs


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Verify speech cuts in an export")
    ap.add_argument("plan", type=Path)
    ap.add_argument("export", type=Path)
    args = ap.parse_args()
    timeline = json.loads(args.plan.read_text())
    report = verify_export_file(timeline, args.export)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
