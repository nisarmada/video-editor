import { useCallback, useEffect, useMemo, useState } from "react";
import type { SpeechBoundary } from "../api/speechCuts";
import { fetchSpeechCutAudit } from "../api/speechCuts";
import { boundaryLabel } from "../timeline/cutWarnings";
import { useTimelineStore } from "../store/timelineStore";

type Props = {
  open: boolean;
  onClose: () => void;
};

const AUDITION_HALF_S = 0.5;

export default function CutCheckModal({ open, onClose }: Props) {
  const timeline = useTimelineStore((s) => s.timeline);
  const applyOperation = useTimelineStore((s) => s.applyOperation);
  const setPlayhead = useTimelineStore((s) => s.setPlayheadSeconds);
  const setPlaying = useTimelineStore((s) => s.setTimelinePlaying);

  const [boundaries, setBoundaries] = useState<SpeechBoundary[]>([]);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const auditionList = useMemo(
    () => boundaries.filter((b) => b.edge === "out"),
    [boundaries],
  );

  const current = auditionList[idx] ?? null;

  const load = useCallback(async () => {
    if (!timeline) return;
    setLoading(true);
    setErr(null);
    try {
      const audit = await fetchSpeechCutAudit(timeline);
      setBoundaries(audit.boundaries);
      setIdx(0);
      useTimelineStore.getState().setSpeechCutAudit(audit);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Audit failed");
    } finally {
      setLoading(false);
    }
  }, [timeline]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const playAround = useCallback(
    (center: number) => {
      const start = Math.max(0, center - AUDITION_HALF_S);
      setPlayhead(start);
      setPlaying(true);
      window.setTimeout(() => {
        useTimelineStore.getState().setTimelinePlaying(false);
        useTimelineStore.getState().setPlayheadSeconds(center);
      }, AUDITION_HALF_S * 2 * 1000);
    },
    [setPlayhead, setPlaying],
  );

  const nudge = async (edge: "in" | "out", sign: 1 | -1) => {
    if (!current) return;
    setBusy(true);
    try {
      await applyOperation({
        operation: "nudge_speech_cut",
        arguments: {
          clip_id: current.clip_id,
          edge,
          delta_ms: sign * 10,
        },
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const refineOne = async () => {
    if (!current) return;
    setBusy(true);
    try {
      await applyOperation({
        operation: "relayout_speech",
        arguments: { clip_ids: [current.clip_id], refine: true },
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div className="cut-check-backdrop" role="presentation" onClick={onClose}>
      <div
        className="cut-check-modal"
        role="dialog"
        aria-labelledby="cut-check-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="cut-check-title">Check speech cuts</h2>
        <p className="cut-check-modal__hint">
          Audition uses timeline playback (±{AUDITION_HALF_S * 1000}ms). Out
          boundaries: {auditionList.length}
        </p>
        {loading && <p>Loading audit…</p>}
        {err && <p className="cut-check-modal__err">{err}</p>}
        {current && !loading && (
          <>
            <dl className="cut-check-modal__meta">
              <dt>Clip</dt>
              <dd>
                {current.clip_id} · {current.edge} @ {current.timeline_time.toFixed(3)}s
              </dd>
              <dt>Status</dt>
              <dd>{boundaryLabel(current.problems)}</dd>
              <dt>Decay retained</dt>
              <dd>
                {current.metrics.decay_retained_ms ?? "—"} ms
                {current.metrics.exported_decay_retained_ms != null
                  ? ` (export ${current.metrics.exported_decay_retained_ms} ms)`
                  : ""}
              </dd>
              <dt>Click score</dt>
              <dd>
                {current.metrics.click_score ?? "—"}
                {current.metrics.exported_click_score != null
                  ? ` (export ${current.metrics.exported_click_score})`
                  : ""}
              </dd>
              <dt>Gap to next</dt>
              <dd>
                {current.metrics.gap_to_next_ms ?? "—"} ms
                {current.metrics.gap_expected_ms != null
                  ? ` (policy ${current.metrics.gap_expected_ms})`
                  : ""}
              </dd>
            </dl>
            <div className="cut-check-modal__actions">
              <button
                type="button"
                disabled={busy || idx <= 0}
                onClick={() => setIdx((i) => Math.max(0, i - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => playAround(current.timeline_time)}
              >
                Play around cut
              </button>
              <button
                type="button"
                disabled={busy || idx >= auditionList.length - 1}
                onClick={() =>
                  setIdx((i) => Math.min(auditionList.length - 1, i + 1))
                }
              >
                Next
              </button>
            </div>
            <div className="cut-check-modal__nudge">
              <span>Nudge out</span>
              <button type="button" disabled={busy} onClick={() => void nudge("out", -1)}>
                −10ms
              </button>
              <button type="button" disabled={busy} onClick={() => void nudge("out", 1)}>
                +10ms
              </button>
              <span>Nudge in</span>
              <button type="button" disabled={busy} onClick={() => void nudge("in", -1)}>
                −10ms
              </button>
              <button type="button" disabled={busy} onClick={() => void nudge("in", 1)}>
                +10ms
              </button>
              <button type="button" disabled={busy} onClick={() => void refineOne()}>
                Re-run refine (this clip)
              </button>
            </div>
          </>
        )}
        <div className="cut-check-modal__footer">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
