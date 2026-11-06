import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  clipDisplayName,
  clipTimelineDuration,
  timelineEnd,
  trackClipClass,
} from "../timeline/duration";
import {
  MAX_PX_PER_SEC,
  MIN_PX_PER_SEC,
  useTimelineStore,
} from "../store/timelineStore";
import { canMutateTimeline } from "../store/timelineMutation";
import { formatTimecode } from "../utils/timeFormat";

const LABEL_WIDTH = 88;
const RULER_HEIGHT = 28;
const TRACK_HEIGHT = 48;

function rulerStepSeconds(pxPerSecond: number): number {
  if (pxPerSecond >= 80) return 1;
  if (pxPerSecond >= 40) return 2;
  if (pxPerSecond >= 24) return 5;
  return 10;
}

export default function TimelinePanel() {
  const timeline = useTimelineStore((s) => s.timeline);
  const loading = useTimelineStore((s) => s.timelineLoading);
  const error = useTimelineStore((s) => s.timelineError);
  const playhead = useTimelineStore((s) => s.playheadSeconds);
  const pxPerSecond = useTimelineStore((s) => s.pxPerSecond);
  const loadPlan = useTimelineStore((s) => s.loadPlan);
  const setPlayhead = useTimelineStore((s) => s.setPlayheadSeconds);
  const setPxPerSecond = useTimelineStore((s) => s.setPxPerSecond);
  const setTimelinePlaying = useTimelineStore((s) => s.setTimelinePlaying);
  const currentPlanName = useTimelineStore((s) => s.currentPlanName);

  const selectedClipId = useTimelineStore((s) => s.selectedClipId);
  const setSelectedClipId = useTimelineStore((s) => s.setSelectedClipId);
  const undoStack = useTimelineStore((s) => s.undoStack);
  const redoStack = useTimelineStore((s) => s.redoStack);
  const applyInProgress = useTimelineStore((s) => s.applyOperationInProgress);
  const dragInProgress = useTimelineStore((s) => s.dragInProgress);
  const opErrorMessage = useTimelineStore((s) => s.opErrorMessage);
  const clearOpError = useTimelineStore((s) => s.clearOpError);
  const undo = useTimelineStore((s) => s.undo);
  const redo = useTimelineStore((s) => s.redo);
  const splitAtPlayhead = useTimelineStore((s) => s.splitAtPlayhead);
  const deleteSelectedClip = useTimelineStore((s) => s.deleteSelectedClip);

  const rulerRef = useRef<HTMLDivElement>(null);

  const canUndo = undoStack.length > 0;
  const canRedo = redoStack.length > 0;
  const busy = !canMutateTimeline({
    applyOperationInProgress: applyInProgress,
    dragInProgress,
  });


  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey || e.key.toLowerCase() !== "z") return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable)
      ) {
        return;
      }
      e.preventDefault();
      if (busy) return;
      if (e.shiftKey) {
        void redo();
      } else {
        void undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, undo, redo]);

  const duration = useMemo(
    () => (timeline ? timelineEnd(timeline) : 0),
    [timeline],
  );

  const contentWidth = Math.max(duration * pxPerSecond, 400);
  const totalWidth = LABEL_WIDTH + contentWidth;

  const ticks = useMemo(() => {
    const step = rulerStepSeconds(pxPerSecond);
    const max = Math.max(duration, step);
    const list: number[] = [];
    for (let t = 0; t <= max + 0.001; t += step) {
      list.push(t);
    }
    return list;
  }, [duration, pxPerSecond]);

  const onRulerClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const el = rulerRef.current;
      if (!el) return;
      setTimelinePlaying(false);
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const t = x / pxPerSecond;
      setPlayhead(Math.min(Math.max(0, t), duration || t));
    },
    [pxPerSecond, setPlayhead, duration, setTimelinePlaying],
  );

  const onClipClick = useCallback(
    (e: React.MouseEvent, clipId: string) => {
      e.stopPropagation();
      setSelectedClipId(clipId);
    },
    [setSelectedClipId],
  );

  const playheadLeft = LABEL_WIDTH + playhead * pxPerSecond;

  return (
    <div className="lower-workspace">
      <div className="timeline-toolbar" aria-label="Timeline view">
        <span className="timeline-toolbar__plan">
          Timeline: {currentPlanName}.json
        </span>
        <button
          type="button"
          className="timeline-toolbar__tool timeline-toolbar__tool--text"
          disabled={busy || !canUndo}
          onClick={() => void undo()}
          title="Undo (⌘Z)"
        >
          Undo
        </button>
        <button
          type="button"
          className="timeline-toolbar__tool timeline-toolbar__tool--text"
          disabled={busy || !canRedo}
          onClick={() => void redo()}
          title="Redo (⌘⇧Z)"
        >
          Redo
        </button>
        <div className="timeline-toolbar__sep" />
        <button
          type="button"
          className="timeline-toolbar__tool timeline-toolbar__tool--text"
          disabled={busy || !selectedClipId}
          onClick={() => void splitAtPlayhead().catch(() => {})}
          title="Split at playhead"
        >
          Split
        </button>
        <button
          type="button"
          className="timeline-toolbar__tool timeline-toolbar__tool--text"
          disabled={busy || !selectedClipId}
          onClick={() => void deleteSelectedClip().catch(() => {})}
          title="Delete selected clip"
        >
          Del
        </button>
        <div className="timeline-toolbar__sep" />
        <div className="timeline-toolbar__zoom">
          <span className="timeline-toolbar__zoom-label">Zoom</span>
          <input
            type="range"
            className="timeline-toolbar__zoom-slider"
            min={MIN_PX_PER_SEC}
            max={MAX_PX_PER_SEC}
            step={4}
            value={pxPerSecond}
            onChange={(e) => setPxPerSecond(Number(e.target.value))}
            aria-label="Timeline zoom"
          />
        </div>
        <span className="timeline-toolbar__label">
          Playhead {formatTimecode(playhead)}
          {duration > 0 ? ` · ${duration.toFixed(1)}s total` : ""}
        </span>
      </div>

      {opErrorMessage && (
        <div className="timeline-op-error" role="alert">
          <span>{opErrorMessage}</span>
          <button type="button" className="link-btn" onClick={clearOpError}>
            Dismiss
          </button>
        </div>
      )}

      <div className="timeline-area timeline-area--loaded">
        {loading && <p className="panel-message">Loading timeline…</p>}
        {error && (
          <p className="panel-message panel-message--error">
            {error}
            <button
              type="button"
              className="link-btn"
              onClick={() => void loadPlan()}
            >
              Retry
            </button>
          </p>
        )}
        {!loading && !error && timeline && (
          <div
            className="timeline-viewport"
            onClick={() => setSelectedClipId(null)}
            role="presentation"
          >
            <div
              className="timeline-canvas"
              style={{ width: totalWidth, minHeight: "100%" }}
            >
              <div
                className="timeline-playhead"
                style={{ left: playheadLeft }}
                aria-hidden
              />

              <div className="timeline-ruler-row">
                <div
                  className="track-label track-label--sticky"
                  style={{ width: LABEL_WIDTH }}
                >
                  Time
                </div>
                <div
                  ref={rulerRef}
                  className="timeline-ruler timeline-ruler--interactive"
                  style={{ width: contentWidth, height: RULER_HEIGHT }}
                  onClick={onRulerClick}
                  role="slider"
                  aria-valuenow={playhead}
                  aria-valuemin={0}
                  aria-valuemax={duration}
                  aria-label="Timeline ruler"
                >
                  {ticks.map((t) => (
                    <span
                      key={t}
                      className="timeline-ruler__tick"
                      style={{ left: t * pxPerSecond }}
                    >
                      {t}s
                    </span>
                  ))}
                </div>
              </div>

              {timeline.tracks.map((track) => (
                <div className="track-row" key={track.id}>
                  <div
                    className="track-label track-label--sticky"
                    style={{ width: LABEL_WIDTH }}
                  >
                    {track.label ?? track.type}
                  </div>
                  <div
                    className="track-lane track-lane--timeline"
                    style={{ width: contentWidth, height: TRACK_HEIGHT }}
                  >
                    {(track.clips ?? []).map((clip) => {
                      const start = clip.timeline_start;
                      const dur = clipTimelineDuration(clip, track.type);
                      const left = start * pxPerSecond;
                      const width = Math.max(dur * pxPerSecond, 4);
                      const selected = clip.id === selectedClipId;
                      return (
                        <div
                          key={clip.id}
                          role="button"
                          tabIndex={0}
                          className={
                            trackClipClass(track.type) +
                            (selected ? " tl-clip--selected" : "")
                          }
                          style={{ left, width }}
                          title={clipDisplayName(clip, track.type)}
                          onClick={(e) => onClipClick(e, clip.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setSelectedClipId(clip.id);
                            }
                          }}
                        >
                          {clipDisplayName(clip, track.type)}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
