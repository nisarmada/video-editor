"""
Speech cut boundaries: timeline audit (plan) and problem detection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from speech_layout import gap_duration_s, normalize_gap_after, ordered_speech_clips, track_uses_speech_layout
from timeline_format import clip_timeline_duration

# Stage 4 thresholds (plan-side / clip metadata)
MIN_DECAY_RETAINED_MS = 40.0
MAX_CLICK_SCORE = 0.12
MAX_CUT_ENERGY_DB = -18.0  # hotter than this at cut ≈ still in speech


@dataclass
class BoundaryMetrics:
    gap_to_next_ms: float | None = None
    gap_expected_ms: float | None = None
    decay_retained_ms: float | None = None
    energy_at_cut_db_below_peak: float | None = None
    click_score: float | None = None
    exported_gap_ms: float | None = None
    exported_energy_db: float | None = None
    exported_click_score: float | None = None
    exported_decay_retained_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if v is not None and isinstance(v, float):
                out[k] = round(v, 2) if "ms" in k or k == "click_score" else round(v, 3)
            elif v is not None:
                out[k] = v
        return out


@dataclass
class SpeechBoundary:
    clip_id: str
    track_id: str
    edge: str  # "in" | "out"
    timeline_time: float
    source_time: float | None
    word: str | None = None
    metrics: BoundaryMetrics = field(default_factory=BoundaryMetrics)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "track_id": self.track_id,
            "edge": self.edge,
            "timeline_time": round(self.timeline_time, 4),
            "source_time": round(self.source_time, 4) if self.source_time is not None else None,
            "word": self.word,
            "metrics": self.metrics.as_dict(),
            "problems": list(self.problems),
        }


def _clip_quality_flags(clip: dict) -> list[str]:
    problems: list[str] = []
    q = clip.get("speech_cut_quality")
    if not isinstance(q, dict):
        return problems
    intent = ""
    ci = clip.get("cut_intent")
    if isinstance(ci, dict) and isinstance(ci.get("end"), str):
        intent = ci["end"]
    decay = q.get("decay_retained_ms")
    if isinstance(decay, (int, float)) and intent in ("complete", "") and decay < MIN_DECAY_RETAINED_MS:
        if intent != "fade" and intent != "abrupt":
            problems.append("may_clip_ending")
    click = q.get("click_score")
    if isinstance(click, (int, float)) and click > MAX_CLICK_SCORE:
        problems.append("high_click")
    edb = q.get("energy_at_cut_db_below_peak")
    if isinstance(edb, (int, float)) and edb > MAX_CUT_ENERGY_DB:
        problems.append("hot_cut")
    if clip.get("speech_transition_tight"):
        problems.append("tight_transition")
    return problems


def enumerate_speech_boundaries(timeline: dict) -> list[SpeechBoundary]:
    """Every in/out on audio tracks (speech), timeline order."""
    rows: list[SpeechBoundary] = []
    for tr in timeline.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        tid = str(tr.get("id", "audio"))
        clips = (
            ordered_speech_clips(tr)
            if track_uses_speech_layout(tr)
            else sorted(
                [c for c in tr.get("clips") or [] if isinstance(c, dict)],
                key=lambda c: float(c.get("timeline_start", 0)),
            )
        )
        for i, clip in enumerate(clips):
            if not isinstance(clip, dict):
                continue
            cid = str(clip.get("id", ""))
            try:
                t0 = float(clip["timeline_start"])
                wall = clip_timeline_duration(clip, "audio")
            except (KeyError, TypeError, ValueError):
                continue
            t1 = t0 + wall
            si = float(clip.get("source_in", 0))
            so = float(clip.get("source_out", si))
            q = clip.get("speech_cut_quality") if isinstance(clip.get("speech_cut_quality"), dict) else {}
            m = BoundaryMetrics(
                decay_retained_ms=float(q["decay_retained_ms"]) if "decay_retained_ms" in q else None,
                energy_at_cut_db_below_peak=float(q["energy_at_cut_db_below_peak"])
                if "energy_at_cut_db_below_peak" in q
                else None,
                click_score=float(q["click_score"]) if "click_score" in q else None,
            )
            gap_exp = None
            gap_act = None
            if i + 1 < len(clips):
                nxt = clips[i + 1]
                try:
                    n0 = float(nxt["timeline_start"])
                    gap_act = max(0.0, (n0 - t1) * 1000.0)
                    gap_exp = gap_duration_s(normalize_gap_after(clip.get("gap_after"))) * 1000.0
                except (KeyError, TypeError, ValueError):
                    pass
            m.gap_to_next_ms = gap_act
            m.gap_expected_ms = gap_exp

            out_probs = _clip_quality_flags(clip)
            if gap_act is not None and gap_exp is not None and abs(gap_act - gap_exp) > 3.0:
                out_probs.append("unexpected_gap")

            rows.append(
                SpeechBoundary(
                    clip_id=cid,
                    track_id=tid,
                    edge="in",
                    timeline_time=t0,
                    source_time=si,
                    metrics=BoundaryMetrics(),
                    problems=[],
                )
            )
            rows.append(
                SpeechBoundary(
                    clip_id=cid,
                    track_id=tid,
                    edge="out",
                    timeline_time=t1,
                    source_time=so,
                    metrics=m,
                    problems=out_probs,
                )
            )
    rows.sort(key=lambda b: (b.timeline_time, 0 if b.edge == "in" else 1))
    return rows


def audit_timeline_speech_cuts(timeline: dict) -> dict[str, Any]:
    boundaries = enumerate_speech_boundaries(timeline)
    problem_count = sum(1 for b in boundaries if b.edge == "out" and b.problems)
    summary = ""
    if problem_count:
        summary = (
            f"{problem_count} cut{'s' if problem_count != 1 else ''} may clip endings"
            if any("may_clip_ending" in b.problems for b in boundaries)
            else f"{problem_count} speech cut issue(s)"
        )
    return {
        "boundaries": [b.as_dict() for b in boundaries],
        "problem_count": problem_count,
        "summary": summary,
    }


def merge_export_metrics(
    audit: dict[str, Any],
    export_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach decoded-export measurements by matching clip_id + edge."""
    index = {(r["clip_id"], r["edge"]): r for r in export_rows}
    for b in audit.get("boundaries") or []:
        key = (b.get("clip_id"), b.get("edge"))
        ex = index.get(key)
        if not ex:
            continue
        m = b.setdefault("metrics", {})
        for k, v in ex.get("metrics", {}).items():
            m[k] = v
        for p in ex.get("problems") or []:
            if p not in b.get("problems", []):
                b.setdefault("problems", []).append(p)
    prob = sum(
        1
        for b in audit.get("boundaries") or []
        if b.get("edge") == "out" and b.get("problems")
    )
    audit["problem_count"] = prob
    if prob and not audit.get("summary"):
        audit["summary"] = f"{prob} cut{'s' if prob != 1 else ''} may clip endings"
    return audit
