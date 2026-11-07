#!/usr/bin/env python3
"""
Read-only audit of speech clip boundaries (gaps, word trims, energy vs Whisper).

Usage (repo root):
  python scripts/diagnose_speech_cuts.py
  python scripts/diagnose_speech_cuts.py plans/plan-2.json --wav-dir output/speech_cut_audit
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from statistics import median
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from audio_cut_refine import (  # noqa: E402
    _SourceCache,
    _rms_at,
    _words_in_range,
    acoustic_word_end,
    load_settings,
    refine_clip_bounds,
)
from proxy_media import list_footage_files

WINDOW_S = 0.01


def _db(rms: float) -> float:
    return 20.0 * math.log10(max(rms, 1e-12))


def _boundary_word(covered: list[dict], t: float, *, edge: str) -> dict | None:
    """Word at a trim boundary: first/last in clip span, else whisper token at t."""
    if not covered:
        return None
    if edge == "in":
        return covered[0]
    return covered[-1]

def _word_at_cut(words: list[dict], t: float, *, edge: str) -> dict | None:
    """Fallback when clip span has no words."""
    if edge == "in":
        for w in words:
            if float(w["start"]) >= t - 0.02:
                return w
        for w in reversed(words):
            if float(w["start"]) <= t <= float(w["end"]) + 0.05:
                return w
        return words[0] if words else None
    for w in reversed(words):
        if float(w["start"]) <= t + 0.02:
            return w
    return words[-1] if words else None


def _rms_series(peaks: list, sr: float, t0: float, t1: float, step: float = WINDOW_S) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    t = t0
    while t <= t1 + 1e-9:
        out.append((t, _rms_at(peaks, sr, t)))
        t += step
    return out


def _median_p90(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    s = sorted(values)
    med = median(s)
    idx = min(len(s) - 1, int(math.ceil(0.9 * len(s)) - 1))
    return float(med), float(s[idx])


def _latest_plan(root: Path) -> Path:
    plans = root / "plans"
    candidates = sorted(plans.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("No plans/*.json")
    return candidates[0]


def _resolve_media(root: Path, source: str) -> Path | None:
    rel = source.replace("\\", "/")
    p = root / rel
    return p if p.is_file() else None


def _export_wav(media: Path, center_t: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, center_t - 0.5)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.4f}",
        "-i",
        str(media),
        "-t",
        "1.0",
        "-ac",
        "1",
        "-ar",
        "48000",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def audit_plan(plan_path: Path, root: Path, wav_dir: Path | None) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text())
    cache = _SourceCache(root)
    cfg = load_settings(root)

    rows: list[dict[str, Any]] = []
    wav_paths: list[str] = []

    for track in plan.get("tracks") or []:
        if track.get("type") != "audio":
            continue
        clips = sorted(
            [c for c in track.get("clips") or [] if isinstance(c, dict)],
            key=lambda c: float(c.get("timeline_start", 0)),
        )
        for i, clip in enumerate(clips):
            cid = str(clip.get("id", f"clip{i}"))
            src = str(clip.get("source") or "")
            si = float(clip["source_in"])
            so = float(clip["source_out"])
            tl0 = float(clip.get("timeline_start", 0))
            wall = so - si
            tl1 = tl0 + wall
            rs_in = clip.get("refined_speech_in")
            rs_out = clip.get("refined_speech_out")
            created = str(clip.get("created_by") or "unknown")

            words = cache.words_for(src)
            sr, peaks = cache.peaks_for(src)
            covered = _words_in_range(words, si, so)

            gap_ms: float | None = None
            overlap_ms: float | None = None
            gap_cause = ""
            if i + 1 < len(clips):
                nxt = clips[i + 1]
                nxt_tl = float(nxt.get("timeline_start", 0))
                delta = nxt_tl - tl1
                if delta >= 0:
                    gap_ms = round(delta * 1000, 1)
                    gap_cause = (
                        "planner: next clip timeline_start ahead of prior clip end "
                        "(refinement preserves wall duration via paired in/out slide)"
                    )
                else:
                    overlap_ms = round(-delta * 1000, 1)
                    gap_cause = "timeline overlap (planner placed clips overlapping)"

            # Re-run refine bounds to see if current trims match refinement-only deltas
            room = None
            if i + 1 < len(clips):
                nxt = clips[i + 1]
                room = max(0.0, float(nxt["timeline_start"]) - tl1)
            sim_in, sim_out, sp_in, sp_out, _fin, _fout = refine_clip_bounds(
                si,
                so,
                words,
                peaks,
                sr,
                cfg,
                clip=clip,
                timeline_room_out=room,
            )
            slide_ms = (si - sim_in) * 1000.0
            out_pull_ms = (so - sim_out) * 1000.0

            for boundary, t_src, t_tl in (
                ("in", si, tl0),
                ("out", so, tl1),
            ):
                w = _boundary_word(covered, t_src, edge=boundary) or _word_at_cut(
                    words, t_src, edge=boundary
                )
                w_word = w.get("word") if w else ""
                w_start = float(w["start"]) if w else None
                w_end = float(w["end"]) if w else None
                dist_word_ms = None
                real_end = None
                decay_cut_ms = None
                tail_rms_mean = None

                if boundary == "in" and w_start is not None:
                    dist_word_ms = round((t_src - w_start) * 1000, 1)
                if boundary == "out" and w and w_end is not None:
                    dist_word_ms = round((t_src - w_end) * 1000, 1)
                    wi = words.index(w)
                    _, real_end, _meta = acoustic_word_end(
                        w, words, wi, peaks, sr, cfg
                    )
                    decay_cut_ms = round((real_end - t_src) * 1000, 1)
                    t_lo = max(0.0, t_src - 0.3)
                    tail = _rms_series(peaks, sr, t_lo, t_src)
                    if tail:
                        tail_rms_mean = sum(v for _t, v in tail) / len(tail)

                rms = _rms_at(peaks, sr, t_src)
                causes: list[str] = []
                if boundary == "in":
                    if slide_ms > 1:
                        causes.append(f"refine pulled in {slide_ms:.0f}ms (pre-roll/snap)")
                    else:
                        causes.append("planner source_in (±sub-ms refine)")
                else:
                    if out_pull_ms > 1:
                        causes.append(f"refine pulled out {out_pull_ms:.0f}ms (post-roll/snap/lowest-RMS)")
                    if rs_out and so < float(rs_out) - 0.002:
                        causes.append(
                            f"out before refined_speech_out ({(float(rs_out)-so)*1000:.0f}ms)"
                        )
                    if decay_cut_ms and decay_cut_ms > 5:
                        causes.append(f"energy tail after out (~{decay_cut_ms:.0f}ms uncaptured)")
                    if not causes:
                        causes.append("planner/refine at or past whisper word end")

                row = {
                    "clip_id": cid,
                    "boundary": boundary,
                    "source": src,
                    "source_in": si,
                    "source_out": so,
                    "timeline_start": tl0,
                    "timeline_end": round(tl1, 4),
                    "gap_to_next_ms": gap_ms,
                    "overlap_next_ms": overlap_ms,
                    "gap_cause": gap_cause if boundary == "out" else "",
                    "word": w_word,
                    "word_start_s": w_start,
                    "word_end_s": w_end,
                    "trim_vs_word_ms": dist_word_ms,
                    "energy_real_word_end_s": real_end,
                    "decay_after_out_ms": decay_cut_ms,
                    "tail_rms_mean_300ms": tail_rms_mean,
                    "rms_db_at_boundary": round(_db(rms), 2),
                    "refined_speech_in": rs_in,
                    "refined_speech_out": rs_out,
                    "timeline_start_set_by": "planner"
                    if created == "ai"
                    else f"created_by={created}",
                    "refine_slide_ms": round(slide_ms, 1),
                    "refine_out_delta_ms": round(out_pull_ms, 1),
                    "boundary_causes": "; ".join(causes),
                }
                rows.append(row)

                if wav_dir and boundary == "out":
                    media = _resolve_media(root, src)
                    if media:
                        out_wav = wav_dir / f"{cid}_out_{so:.3f}s.wav"
                        try:
                            _export_wav(media, so, out_wav)
                            wav_paths.append(str(out_wav.resolve()))
                        except subprocess.CalledProcessError:
                            pass
                if wav_dir and boundary == "in":
                    media = _resolve_media(root, src)
                    if media:
                        out_wav = wav_dir / f"{cid}_in_{si:.3f}s.wav"
                        try:
                            _export_wav(media, si, out_wav)
                            wav_paths.append(str(out_wav.resolve()))
                        except subprocess.CalledProcessError:
                            pass

    return {"plan": str(plan_path), "rows": rows, "wav_paths": wav_paths}


def library_whisper_vs_energy(root: Path) -> dict[str, Any]:
    cache = _SourceCache(root)
    cfg = load_settings(root)
    deltas: list[float] = []
    per_file: list[dict[str, Any]] = []

    for clip_path in list_footage_files(root):
        rel = f"footage/{clip_path.name}"
        words = cache.words_for(rel)
        if not words:
            continue
        sr, peaks = cache.peaks_for(rel)
        file_d: list[float] = []
        for w in words:
            we = float(w["end"])
            wi = words.index(w)
            _, ae, _ = acoustic_word_end(w, words, wi, peaks, sr, cfg)
            d_ms = (ae - we) * 1000.0
            if -50 < d_ms < 500:
                file_d.append(d_ms)
                deltas.append(d_ms)
        if file_d:
            med, p90 = _median_p90(file_d)
            per_file.append(
                {"file": clip_path.name, "words": len(file_d), "median_ms": med, "p90_ms": p90}
            )

    med, p90 = _median_p90(deltas)
    return {
        "word_count": len(deltas),
        "median_whisper_to_energy_end_ms": med,
        "p90_whisper_to_energy_end_ms": p90,
        "per_file": per_file,
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    cols = [
        "clip_id",
        "boundary",
        "source_in",
        "source_out",
        "timeline_start",
        "timeline_end",
        "gap_to_next_ms",
        "word",
        "trim_vs_word_ms",
        "decay_after_out_ms",
        "rms_db_at_boundary",
        "boundary_causes",
    ]
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(r.get(c, "")) for c in cols))


def main() -> None:
    parser = argparse.ArgumentParser(description="Speech cut boundary audit")
    parser.add_argument("plan", nargs="?", default=None, help="Plan JSON (default: newest in plans/)")
    parser.add_argument("--root", type=Path, default=_REPO)
    parser.add_argument("--wav-dir", type=Path, default=None, help="Export 1s WAV snippets per boundary")
    parser.add_argument("--json", type=Path, default=None, help="Write full JSON report here")
    args = parser.parse_args()

    root = args.root.resolve()
    plan_path = Path(args.plan) if args.plan else _latest_plan(root)
    wav_dir = args.wav_dir
    if wav_dir is None:
        wav_dir = root / "output" / "speech_cut_audit"

    audit = audit_plan(plan_path, root, wav_dir)
    lib = library_whisper_vs_energy(root)

    layout_note = (
        "Audio clip timeline_start is set by the planner (or user move_clip in the editor). "
        "audio_cut_refine adjusts source_in/source_out only (slide keeps timeline_start fixed). "
        "No other server code auto-layouts speech on the timeline."
    )

    report = {**audit, "library_energy": lib, "timeline_layout_note": layout_note}
    print(f"Plan: {audit['plan']}")
    print_table(audit["rows"])
    print("\n--- Library Whisper word.end → energy tail (ms) ---")
    print(json.dumps(lib, indent=2))
    print("\n--- Timeline layout ---")
    print(layout_note)
    print("\n--- WAV snippets ---")
    for p in audit["wav_paths"]:
        print(p)

    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
