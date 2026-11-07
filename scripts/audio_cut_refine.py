"""
Deterministic narration trim refinement: word-safe in/out, energy onset, speech-only fades.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
import sys

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from index_cache import load_json, transcript_path, waveform_path  # noqa: E402

SETTINGS_KEY = "audio_cut_refine"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "pre_roll_ms": 120,
    "post_roll_ms": 150,
    "snap_window_ms": 80,
    "fade_ms": 15,
    "join_crossfade_ms": 10,
    "energy_disagree_ms": 80,
    "min_clip_s": 0.3,
    # Acoustic word-end (Stage 3)
    "energy_end_db_below_peak": 25.0,
    "energy_low_hold_ms": 30,
    "acoustic_tail_ms": 60,
    "acoustic_scan_max_ms": 500,
    "tight_tail_ms": 25,
}


@dataclass
class CutQualityMetrics:
    clip_id: str
    whisper_end_s: float
    acoustic_end_s: float
    cut_out_s: float
    decay_retained_ms: float
    energy_at_cut_db_below_peak: float
    click_score: float
    transition_tight: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "whisper_end_s": round(self.whisper_end_s, 4),
            "acoustic_end_s": round(self.acoustic_end_s, 4),
            "cut_out_s": round(self.cut_out_s, 4),
            "decay_retained_ms": round(self.decay_retained_ms, 1),
            "energy_at_cut_db_below_peak": round(self.energy_at_cut_db_below_peak, 2),
            "click_score": round(self.click_score, 4),
            "transition_tight": self.transition_tight,
        }


@dataclass
class RefineMove:
    clip_id: str
    track_id: str
    source: str
    old_in: float
    old_out: float
    new_in: float
    new_out: float
    delta_in_ms: float
    delta_out_ms: float
    in_point_rms: float
    quality: CutQualityMetrics | None = None

    def as_dict(self) -> dict[str, Any]:
        d = {
            "clip_id": self.clip_id,
            "track_id": self.track_id,
            "source": self.source,
            "old_in": round(self.old_in, 4),
            "old_out": round(self.old_out, 4),
            "new_in": round(self.new_in, 4),
            "new_out": round(self.new_out, 4),
            "delta_in_ms": round(self.delta_in_ms, 1),
            "delta_out_ms": round(self.delta_out_ms, 1),
            "in_point_rms": round(self.in_point_rms, 8),
        }
        if self.quality is not None:
            d["quality"] = self.quality.as_dict()
        return d


@dataclass
class RefineReport:
    moves: list[RefineMove] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    quality: list[CutQualityMetrics] = field(default_factory=list)

    def summary_line(self) -> str:
        if not self.moves:
            return ""
        parts = [
            f"{m.clip_id} in{m.delta_in_ms:+.0f}ms out{m.delta_out_ms:+.0f}ms"
            for m in self.moves[:12]
        ]
        tail = f" (+{len(self.moves) - 12} more)" if len(self.moves) > 12 else ""
        return "Audio cuts refined: " + ", ".join(parts) + tail


def load_settings(root: Path | None = None) -> dict[str, Any]:
    """Merge app_settings audio_cut_refine with DEFAULTS."""
    cfg = dict(DEFAULTS)
    root = root or Path.cwd()
    path = root / "index" / "app_settings.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text())
            block = raw.get(SETTINGS_KEY) if isinstance(raw, dict) else None
            if isinstance(block, dict):
                cfg.update(block)
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def _resolve_footage_path(source: str, root: Path) -> Path | None:
    if not source or not isinstance(source, str):
        return None
    p = Path(source)
    if p.is_file():
        return p
    p2 = root / source
    if p2.is_file():
        return p2
    if source.startswith("footage/"):
        p3 = root / source
        if p3.is_file():
            return p3
    return None


def flatten_words(transcript: dict | None) -> list[dict[str, Any]]:
    if not isinstance(transcript, dict):
        return []
    words: list[dict[str, Any]] = []
    for seg in transcript.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        for w in seg.get("words") or []:
            if not isinstance(w, dict):
                continue
            try:
                words.append(
                    {
                        "word": str(w.get("word", "")),
                        "start": float(w["start"]),
                        "end": float(w["end"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    words.sort(key=lambda w: w["start"])
    return words


class _SourceCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._words: dict[str, list[dict]] = {}
        self._peaks: dict[str, tuple[float, list]] = {}

    def words_for(self, source: str) -> list[dict]:
        if source in self._words:
            return self._words[source]
        path = _resolve_footage_path(source, self.root)
        if not path:
            self._words[source] = []
            return []
        tr = load_json(transcript_path(path))
        wl = flatten_words(tr if isinstance(tr, dict) else None)
        self._words[source] = wl
        return wl

    def peaks_for(self, source: str) -> tuple[float, list]:
        if source in self._peaks:
            return self._peaks[source]
        path = _resolve_footage_path(source, self.root)
        if not path:
            self._peaks[source] = (100.0, [])
            return 100.0, []
        wf = load_json(waveform_path(path))
        if not isinstance(wf, dict):
            self._peaks[source] = (100.0, [])
            return 100.0, []
        sr = float(wf.get("sample_rate_hz_of_peaks") or 100.0)
        peaks = wf.get("peaks") or []
        if not isinstance(peaks, list):
            peaks = []
        self._peaks[source] = (sr, peaks)
        return sr, peaks


def _rms_at(peaks: list, sr: float, t: float) -> float:
    i = int(t * sr)
    if i < 0 or i >= len(peaks):
        return 0.0
    bucket = peaks[i]
    if not isinstance(bucket, (list, tuple)) or len(bucket) < 2:
        return 0.0
    return max(abs(float(bucket[0])), abs(float(bucket[1])))


def energy_onset_before(
    word_start: float,
    peaks: list,
    sr: float,
    *,
    window_s: float = 0.45,
) -> float:
    """First rise above a local minimum in the window before whisper word start."""
    i_end = int(word_start * sr)
    i_start = max(0, int((word_start - window_s) * sr))
    if i_end <= i_start:
        return word_start
    best_i = i_end
    min_v = float("inf")
    min_i = i_start
    for i in range(i_start, i_end + 1):
        v = _rms_at(peaks, sr, i / sr)
        if v < min_v:
            min_v = v
            min_i = i
    thresh = max(min_v * 3.0, min_v + 1e-4)
    for i in range(min_i, i_end + 1):
        if _rms_at(peaks, sr, i / sr) >= thresh:
            return i / sr
    return word_start


def _lowest_rms_time(peaks: list, sr: float, t0: float, t1: float) -> float:
    if t1 <= t0:
        return t0
    t0 = max(0.0, t0)
    step = 1.0 / sr
    best_t = t0
    best_v = float("inf")
    t = t0
    while t <= t1 + 1e-9:
        v = _rms_at(peaks, sr, t)
        if v < best_v:
            best_v = v
            best_t = t
        t += step
    return best_t


def _ratio_db_below_peak(rms: float, peak: float) -> float:
    if peak <= 1e-12:
        return -120.0
    return 20.0 * math.log10(max(rms, 1e-12) / peak)


def _peak_rms_in_range(peaks: list, sr: float, t0: float, t1: float) -> float:
    step = max(1.0 / sr, 0.005)
    peak = 0.0
    t = t0
    while t <= t1 + 1e-9:
        peak = max(peak, _rms_at(peaks, sr, t))
        t += step
    return peak


def acoustic_word_end(
    word: dict,
    words: list[dict],
    word_index: int,
    peaks: list,
    sr: float,
    cfg: dict[str, Any],
    *,
    cut_intent_end: str | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """
    Acoustic out time (absolute seconds) and acoustic decay landmark.
    Returns (recommended_cut_out, acoustic_end_landmark, meta).
    """
    ws = float(word["start"])
    we = float(word["end"])
    db = float(cfg.get("energy_end_db_below_peak", 25.0))
    thresh_ratio = 10.0 ** (-db / 20.0)
    low_hold = float(cfg.get("energy_low_hold_ms", 30)) / 1000.0
    tail_s = float(cfg.get("acoustic_tail_ms", 60)) / 1000.0
    tight_tail = float(cfg.get("tight_tail_ms", 25)) / 1000.0
    scan_max = float(cfg.get("acoustic_scan_max_ms", 500)) / 1000.0
    step = max(1.0 / sr, 0.01)

    next_start: float | None = None
    if word_index + 1 < len(words):
        next_start = float(words[word_index + 1]["start"])
    scan_end = we + scan_max
    if next_start is not None:
        scan_end = min(scan_end, next_start - 0.002)
    scan_end = max(scan_end, we + 0.001)

    peak = _peak_rms_in_range(peaks, sr, ws, scan_end)
    meta: dict[str, Any] = {
        "whisper_end": we,
        "peak_rms": peak,
        "tight": False,
    }
    if peak <= 1e-12:
        cut = min(we + tail_s, scan_end)
        return cut, we, meta

    thresh = peak * thresh_ratio

    if cut_intent_end in ("abrupt", "fade"):
        snap = float(cfg.get("snap_window_ms", 80)) / 1000.0
        valley = _lowest_rms_time(peaks, sr, we + 0.001, min(we + snap, scan_end))
        cut = min(valley + tight_tail, scan_end)
        meta["intent_early"] = True
        return cut, valley, meta

    valley_t = we
    valley_v = float("inf")
    low_since: float | None = None
    sustain_from: float | None = None
    t = we
    while t <= scan_end + 1e-9:
        v = _rms_at(peaks, sr, t)
        if v < valley_v:
            valley_v = v
            valley_t = t
        if v <= thresh:
            if low_since is None:
                low_since = t
            if t - low_since >= low_hold - 1e-9:
                sustain_from = low_since
                break
        else:
            low_since = None
        t += step

    acoustic_landmark = sustain_from if sustain_from is not None else valley_t

    tight = False
    if next_start is not None and next_start < acoustic_landmark + tail_s + 0.005:
        tight = True
        acoustic_landmark = _lowest_rms_time(peaks, sr, we + 0.001, next_start - 0.002)
        cut = min(acoustic_landmark + tight_tail, next_start - 0.002)
    else:
        cut = min(acoustic_landmark + tail_s, scan_end)

    meta["tight"] = tight
    meta["acoustic_landmark"] = acoustic_landmark
    meta["sustain_from"] = sustain_from
    return cut, acoustic_landmark, meta


def compute_cut_quality(
    *,
    clip_id: str,
    peaks: list,
    sr: float,
    whisper_end: float,
    acoustic_end: float,
    cut_out: float,
    transition_tight: bool,
) -> CutQualityMetrics:
    """Post-cut metrics: decay retained, relative energy, simple click score."""
    win = 0.02
    rms_cut = _rms_at(peaks, sr, max(cut_out - 0.001, 0.0))
    rms_before = _rms_at(peaks, sr, max(cut_out - win, 0.0))
    peak = _peak_rms_in_range(
        peaks, sr, max(0.0, whisper_end - 0.4), min(cut_out + 0.05, whisper_end + 0.6)
    )
    decay_ms = max(0.0, (cut_out - whisper_end) * 1000.0)
    click = abs(rms_cut - rms_before) / max(peak, 1e-9)
    return CutQualityMetrics(
        clip_id=clip_id,
        whisper_end_s=whisper_end,
        acoustic_end_s=acoustic_end,
        cut_out_s=cut_out,
        decay_retained_ms=decay_ms,
        energy_at_cut_db_below_peak=_ratio_db_below_peak(rms_cut, peak),
        click_score=click,
        transition_tight=transition_tight,
    )


def _words_in_range(words: list[dict], si: float, so: float) -> list[dict]:
    return [w for w in words if float(w["end"]) > si + 1e-6 and float(w["start"]) < so - 1e-6]


def _speech_safe_fades(
    clip: dict | None,
    *,
    new_in: float,
    new_out: float,
    whisper_start: float,
    acoustic_end: float,
    cfg: dict[str, Any],
) -> tuple[float, float]:
    """
    Fade-in before speech; fade-out only in the safety tail after acoustic word end
    so audible decay is not ducked by the fade curve.
    """
    default = min(float(cfg["fade_ms"]) / 1000.0, 0.02)
    lead = max(0.0, whisper_start - new_in)
    # Tail is strictly after the detected acoustic decay landmark.
    tail = max(0.0, new_out - acoustic_end)
    max_fin = max(0.0, lead - 0.004)
    max_fout = max(0.0, tail - 0.001)

    raw_in = clip.get("audio_fade_in") if clip else None
    raw_out = clip.get("audio_fade_out") if clip else None

    if raw_in is not None:
        try:
            fin = float(raw_in)
        except (TypeError, ValueError):
            fin = min(default, max_fin)
        else:
            fin = min(fin, max_fin) if max_fin > 1e-6 else 0.0
    else:
        fin = min(default, max_fin)

    if raw_out is not None:
        try:
            fout = float(raw_out)
        except (TypeError, ValueError):
            fout = min(default, max_fout)
        else:
            fout = min(fout, max_fout) if max_fout > 1e-6 else 0.0
    else:
        fout = min(default, max_fout)
    # Fade must not extend backward into active speech.
    if fout > tail + 1e-6:
        fout = max(0.0, tail)
    return fin, fout


def refine_clip_bounds(
    source_in: float,
    source_out: float,
    words: list[dict],
    peaks: list,
    sr: float,
    cfg: dict[str, Any],
    *,
    clip: dict | None = None,
    timeline_room_out: float | None = None,
    preserve_timeline_wall: bool = True,
) -> tuple[float, float, float, float, float, float]:
    """
    Return (new_in, new_out, speech_start, speech_end, fade_in, fade_out).
    speech_* are absolute times in the source file.
    With preserve_timeline_wall, slide keeps wall length for legacy timelines.
    Speech EDL layout uses preserve_timeline_wall=False so trims drive duration.
    """
    covered = _words_in_range(words, source_in, source_out)
    if not covered:
        fin, fout = _speech_safe_fades(
            clip,
            new_in=source_in,
            new_out=source_out,
            whisper_start=source_in,
            acoustic_end=source_out,
            cfg=cfg,
        )
        return source_in, source_out, source_in, source_out, fin, fout

    fw, lw = covered[0], covered[-1]
    whisper_start = float(fw["start"])
    speech_end = float(lw["end"])
    intent_end: str | None = None
    if clip and isinstance(clip.get("cut_intent"), dict):
        raw = clip["cut_intent"].get("end")
        if isinstance(raw, str):
            intent_end = raw
    onset_target = whisper_start

    onset = energy_onset_before(whisper_start, peaks, sr)
    disagree = float(cfg["energy_disagree_ms"]) / 1000.0
    if whisper_start - onset >= disagree:
        onset_target = min(whisper_start, onset)

    pre = float(cfg["pre_roll_ms"]) / 1000.0
    post = float(cfg["post_roll_ms"]) / 1000.0
    snap_w = float(cfg["snap_window_ms"]) / 1000.0
    max_pull = pre + snap_w
    if clip and clip.get("audio_fade_in") is not None:
        try:
            fin_req = float(clip["audio_fade_in"])
            max_pull = max(max_pull, fin_req + 0.015)
        except (TypeError, ValueError):
            pass

    fw_i = words.index(fw)
    if fw_i > 0:
        prev_end = float(words[fw_i - 1]["end"])
        gap = onset_target - prev_end
        earliest = prev_end + 0.002
        # Tight gap only: cut near silence mid; long gap → pre-roll before onset only.
        if gap <= pre + 0.04:
            target_in = (prev_end + onset_target) * 0.5
            target_in = max(target_in, earliest)
        else:
            target_in = onset_target - pre
            target_in = max(target_in, earliest)
    else:
        target_in = max(0.0, onset_target - pre)

    snap_lo = max(target_in - snap_w, onset_target - max_pull)
    snap_hi = whisper_start - 0.001
    ideal_in = _lowest_rms_time(peaks, sr, snap_lo, snap_hi)

    # Never pull farther than max_pull from the planner in-point.
    earliest_allowed = max(0.0, source_in - max_pull)
    if fw_i > 0:
        earliest_allowed = max(earliest_allowed, float(words[fw_i - 1]["end"]) + 0.002)
    new_in = min(
        whisper_start - 0.001,
        source_in,
        max(earliest_allowed, ideal_in),
    )

    lw_i = words.index(lw)
    next_cap = float(words[lw_i + 1]["start"]) - 0.002 if lw_i + 1 < len(words) else None

    acoustic_cut, acoustic_landmark, out_meta = acoustic_word_end(
        lw, words, lw_i, peaks, sr, cfg, cut_intent_end=intent_end
    )
    max_out = acoustic_cut
    if next_cap is not None:
        max_out = min(max_out, next_cap)
    max_out = max(max_out, new_in + 0.001)

    if preserve_timeline_wall:
        slide = max(0.0, source_in - new_in)
        new_out = source_out - slide
        wall_after = source_out - source_in
        acoustic_cap = new_in + wall_after
        if timeline_room_out is not None and timeline_room_out > 1e-6:
            extra_room = min(
                timeline_room_out,
                max(0.0, acoustic_cut - new_out),
            )
            new_out = min(max_out, new_out + extra_room)
        if intent_end not in ("abrupt", "fade"):
            new_out = max(
                new_out,
                min(acoustic_cut, acoustic_cap, max_out),
            )
        new_out = min(new_out, max_out, acoustic_cap)
    else:
        new_out = min(max(acoustic_cut, new_in + 0.001), max_out)

    min_len = float(cfg.get("min_clip_s", 0.3))
    if new_out - new_in < min_len:
        new_in = max(0.0, new_out - min_len)

    if clip is not None:
        if out_meta.get("tight"):
            clip["speech_transition_tight"] = True
        elif "speech_transition_tight" in clip:
            clip.pop("speech_transition_tight", None)
        clip["acoustic_word_end"] = round(acoustic_landmark, 4)

    fin, fout = _speech_safe_fades(
        clip,
        new_in=new_in,
        new_out=new_out,
        whisper_start=whisper_start,
        acoustic_end=acoustic_landmark,
        cfg=cfg,
    )
    return new_in, new_out, whisper_start, speech_end, fin, fout


def _sync_caption_trims(
    tl: dict,
    *,
    source: str,
    old_in: float,
    old_out: float,
    new_in: float,
    new_out: float,
) -> None:
    """Mirror source_in/out on caption clips that matched the pre-refine audio span."""
    for tr in tl.get("tracks") or []:
        if tr.get("type") != "caption":
            continue
        for c in tr.get("clips") or []:
            if c.get("source") != source:
                continue
            try:
                si = float(c.get("source_in", -1))
                so = float(c.get("source_out", -2))
            except (TypeError, ValueError):
                continue
            if abs(si - old_in) < 0.02 and abs(so - old_out) < 0.02:
                c["source_in"] = new_in
                c["source_out"] = new_out


def _apply_join_crossfades(track_clips: list[dict], join_s: float) -> None:
    """Adjacent timeline clips: one short crossfade instead of stacked hard fades."""
    if join_s <= 0:
        return
    ordered = sorted(
        [c for c in track_clips if isinstance(c, dict)],
        key=lambda c: float(c.get("timeline_start", 0)),
    )
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if a.get("source") != b.get("source"):
            continue
        a_end = float(a.get("timeline_start", 0)) + (
            float(a.get("source_out", 0)) - float(a.get("source_in", 0))
        )
        b_start = float(b.get("timeline_start", 0))
        if abs(a_end - b_start) > 0.03:
            continue
        half = join_s * 0.5
        a["audio_fade_out"] = half
        b_fin = b.get("audio_fade_in")
        if b_fin is None or float(b_fin) <= half + 1e-6:
            b["audio_fade_in"] = half
        a["audio_join_crossfade"] = join_s
        b["audio_join_crossfade"] = join_s


def refine_timeline_audio_cuts(
    timeline: dict,
    *,
    root: Path | None = None,
    settings: dict[str, Any] | None = None,
    clip_ids: set[str] | None = None,
    preserve_timeline_wall: bool | None = None,
) -> tuple[dict, RefineReport]:
    """Refine all (or selected) clips on audio tracks. Returns deep-copied timeline + report."""
    cfg = dict(DEFAULTS)
    if settings:
        cfg.update(settings)
    if not cfg.get("enabled", True):
        return copy.deepcopy(timeline), RefineReport()

    root = root or Path.cwd()
    try:
        from speech_layout import track_uses_speech_layout
    except ImportError:
        track_uses_speech_layout = lambda _tr: False  # type: ignore[assignment]

    cache = _SourceCache(root)
    tl = copy.deepcopy(timeline)
    report = RefineReport()
    join_s = float(cfg["join_crossfade_ms"]) / 1000.0

    def _timeline_room(clips: list[dict], clip: dict) -> float | None:
        ts = float(clip.get("timeline_start", 0))
        wall = float(clip["source_out"]) - float(clip["source_in"])
        end = ts + wall
        nxt = None
        for c in clips:
            if c is clip or not isinstance(c, dict):
                continue
            cts = float(c.get("timeline_start", 0))
            if cts > ts + 1e-6:
                if nxt is None or cts < float(nxt.get("timeline_start", 0)):
                    nxt = c
        if nxt is None:
            return None
        return max(0.0, float(nxt["timeline_start"]) - end)

    for tr in tl.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        tid = str(tr.get("id", "audio"))
        clips = tr.get("clips") or []
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            cid = str(clip.get("id", ""))
            if clip_ids is not None and cid not in clip_ids:
                continue
            src = clip.get("source")
            if not src or not isinstance(src, str):
                report.skipped.append(f"{cid}: no source")
                continue
            try:
                si = float(clip["source_in"])
                so = float(clip["source_out"])
            except (KeyError, TypeError, ValueError):
                report.skipped.append(f"{cid}: bad trims")
                continue
            words = cache.words_for(src)
            if not words:
                report.skipped.append(f"{cid}: no transcript words")
                continue
            sr, peaks = cache.peaks_for(src)
            speech_layout = track_uses_speech_layout(tr)
            wall_preserve = (
                preserve_timeline_wall
                if preserve_timeline_wall is not None
                else (not speech_layout)
            )
            room = None if speech_layout else _timeline_room(clips, clip)
            new_in, new_out, _ss, _se, fin, fout = refine_clip_bounds(
                si,
                so,
                words,
                peaks,
                sr,
                cfg,
                clip=clip,
                timeline_room_out=room,
                preserve_timeline_wall=wall_preserve,
            )
            in_rms = _rms_at(peaks, sr, new_in)
            acoustic_land = float(clip.get("acoustic_word_end", _se))
            quality = compute_cut_quality(
                clip_id=cid,
                peaks=peaks,
                sr=sr,
                whisper_end=_se,
                acoustic_end=acoustic_land,
                cut_out=new_out,
                transition_tight=bool(clip.get("speech_transition_tight")),
            )
            clip["speech_cut_quality"] = quality.as_dict()
            report.quality.append(quality)
            moved = abs(new_in - si) >= 0.0005 or abs(new_out - so) >= 0.0005
            if not moved:
                clip["refined_speech_in"] = round(_ss, 4)
                clip["refined_speech_out"] = round(_se, 4)
                continue
            clip["source_in"] = round(new_in, 4)
            clip["source_out"] = round(new_out, 4)
            if fin > 0:
                clip["audio_fade_in"] = round(fin, 4)
            elif "audio_fade_in" in clip and fin <= 0:
                clip.pop("audio_fade_in", None)
            if fout > 0:
                clip["audio_fade_out"] = round(fout, 4)
            elif "audio_fade_out" in clip and fout <= 0:
                clip.pop("audio_fade_out", None)
            clip["refined_speech_in"] = round(_ss, 4)
            clip["refined_speech_out"] = round(_se, 4)
            _sync_caption_trims(
                tl,
                source=src,
                old_in=si,
                old_out=so,
                new_in=new_in,
                new_out=new_out,
            )
            report.moves.append(
                RefineMove(
                    clip_id=cid,
                    track_id=tid,
                    source=src,
                    old_in=si,
                    old_out=so,
                    new_in=new_in,
                    new_out=new_out,
                    delta_in_ms=(new_in - si) * 1000.0,
                    delta_out_ms=(new_out - so) * 1000.0,
                    in_point_rms=in_rms,
                    quality=quality,
                )
            )
        _apply_join_crossfades(clips, join_s)

    # Inner clips: re-apply join may have shortened fades — keep speech-safe fades.
    for tr in tl.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict) or "refined_speech_in" not in clip:
                continue
            src = clip.get("source")
            if not isinstance(src, str):
                continue
            words = cache.words_for(src)
            if not words:
                continue
            si = float(clip["source_in"])
            so = float(clip["source_out"])
            acoustic = float(
                clip.get("acoustic_word_end", clip.get("refined_speech_out"))
            )
            fin, fout = _speech_safe_fades(
                clip,
                new_in=si,
                new_out=so,
                whisper_start=float(clip["refined_speech_in"]),
                acoustic_end=acoustic,
                cfg=cfg,
            )
            if fin > 0:
                clip["audio_fade_in"] = round(fin, 4)
            if fout > 0:
                clip["audio_fade_out"] = round(fout, 4)

    return tl, report


def check_word_clipped_at_cuts(
    timeline: dict,
    *,
    root: Path | None = None,
) -> list[str]:
    """Quality warnings: in-point inside a word or too little pre-speech silence."""
    root = root or Path.cwd()
    cache = _SourceCache(root)
    cfg = load_settings(root)
    pre = float(cfg["pre_roll_ms"]) / 1000.0
    warnings: list[str] = []

    for tr in timeline.get("tracks") or []:
        if tr.get("type") != "audio":
            continue
        tid = str(tr.get("id", "audio"))
        for i, clip in enumerate(tr.get("clips") or []):
            if not isinstance(clip, dict):
                continue
            src = clip.get("source")
            if not isinstance(src, str):
                continue
            try:
                si = float(clip["source_in"])
            except (KeyError, TypeError, ValueError):
                continue
            words = cache.words_for(src)
            if not words:
                continue
            for w in words:
                ws, we = float(w["start"]), float(w["end"])
                if ws + 1e-4 < si < we - 1e-4:
                    warnings.append(
                        f"word clipped at cut: track {tid} clip {i} ({clip.get('id')}) "
                        f"in-point {si:.3f}s inside {w['word']!r} [{ws:.2f}-{we:.2f}]"
                    )
                    break
            fw = next((w for w in words if float(w["end"]) > si), None)
            if fw and float(fw["start"]) - si < pre * 0.35:
                warnings.append(
                    f"word clipped at cut: track {tid} clip {i} ({clip.get('id')}) "
                    f"only {(float(fw['start']) - si) * 1000:.0f}ms before "
                    f"{fw['word']!r} (want ~{cfg['pre_roll_ms']}ms pre-roll)"
                )
    return warnings
