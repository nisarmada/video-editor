import type { CSSProperties } from "react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  clipDisplayName,
  clipTimelineDuration,
  timelineEnd,
  trackClipClass,
} from "../timeline/duration";
import {
  FOOTAGE_DRAG_MIME,
  MIN_CLIP_SECONDS,
  TIMELINE_SNAP_SEC,
} from "../timeline/dragConstants";
import {
  MAX_PX_PER_SEC,
  MIN_PX_PER_SEC,
  useTimelineStore,
} from "../store/timelineStore";
import { canMutateTimeline } from "../store/timelineMutation";
import type { FootageClip } from "../api/footage";
import type { TrackType } from "../timeline/types";
import { formatTimecode } from "../utils/timeFormat";
import ClipWaveformCanvas from "./ClipWaveformCanvas";
import { useWaveformCacheStore } from "../store/waveformCacheStore";

const LABEL_WIDTH = 88;
const RULER_HEIGHT = 28;
const TRACK_HEIGHT = 48;

function rulerStepSeconds(pxPerSecond: number): number {
  if (pxPerSecond >= 80) return 1;
  if (pxPerSecond >= 40) return 2;
  if (pxPerSecond >= 24) return 5;
  return 10;
}

function snapTimelineSec(sec: number): number {
  const s = Math.round(sec / TIMELINE_SNAP_SEC) * TIMELINE_SNAP_SEC;
  return Math.max(0, s);
}

function laneContentXFromClient(
  clientX: number,
  laneEl: HTMLElement,
  viewportEl: HTMLElement | null,
): number {
  const laneRect = laneEl.getBoundingClientRect();
  const scrollLeft = viewportEl?.scrollLeft ?? 0;
  return clientX - laneRect.left + scrollLeft;
}

function findTrackUnderPoint(
  viewportEl: HTMLElement,
  clientY: number,
): { trackId: string; trackType: TrackType } | null {
  const lanes = viewportEl.querySelectorAll<HTMLElement>(
    "[data-track-lane-id]",
  );
  for (const el of lanes) {
    const r = el.getBoundingClientRect();
    if (clientY >= r.top && clientY <= r.bottom) {
      const id = el.dataset.trackLaneId;
      const t = el.dataset.trackType as TrackType | undefined;
      if (id && t) return { trackId: id, trackType: t };
    }
  }
  return null;
}

type FootageDragPayload = Pick<FootageClip, "name" | "source" | "duration_seconds">;

type PointerDragState = {
  clipId: string;
  originTrackId: string;
  originTrackType: TrackType;
  pointerId: number;
  startClientX: number;
  originTimelineStart: number;
};

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
  const setDragInProgress = useTimelineStore((s) => s.setDragInProgress);
  const opErrorMessage = useTimelineStore((s) => s.opErrorMessage);
  const clearOpError = useTimelineStore((s) => s.clearOpError);
  const undo = useTimelineStore((s) => s.undo);
  const redo = useTimelineStore((s) => s.redo);
  const splitAtPlayhead = useTimelineStore((s) => s.splitAtPlayhead);
  const deleteSelectedClip = useTimelineStore((s) => s.deleteSelectedClip);
  const applyOperation = useTimelineStore((s) => s.applyOperation);

  const rulerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const ensureWaveform = useWaveformCacheStore((s) => s.ensureFetch);

  /** Pixels available for lanes (viewport minus sticky label); stretches short edits to full width. */
  const [viewportLanePx, setViewportLanePx] = useState(800);

  const [dropIndicatorSec, setDropIndicatorSec] = useState<number | null>(null);
  const [pointerDrag, setPointerDrag] = useState<PointerDragState | null>(null);

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

  useLayoutEffect(() => {
    const el = viewportRef.current;
    if (!el || loading || error || !timeline) return;

    const measure = () => {
      const w = el.clientWidth - LABEL_WIDTH;
      setViewportLanePx(Math.max(0, w));
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [loading, error, timeline]);

  const totalClipCount = useMemo(() => {
    if (!timeline?.tracks) return 0;
    return timeline.tracks.reduce((n, t) => n + (t.clips?.length ?? 0), 0);
  }, [timeline]);

  /** Lane spans at least the edited duration or the visible area so zoom uses full width. */
  const laneWidth = Math.max(duration * pxPerSecond, viewportLanePx, 200);
  const totalWidth = LABEL_WIDTH + laneWidth;
  const visibleSeconds = laneWidth / pxPerSecond;

  const ticks = useMemo(() => {
    const step = rulerStepSeconds(pxPerSecond);
    const max = Math.max(duration, visibleSeconds, step);
    const list: number[] = [];
    for (let t = 0; t <= max + 0.001; t += step) {
      list.push(t);
    }
    return list;
  }, [duration, pxPerSecond, visibleSeconds]);

  const onRulerClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const el = rulerRef.current;
      if (!el) return;
      setTimelinePlaying(false);
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const t = x / pxPerSecond;
      const maxT = duration > 0 ? duration : visibleSeconds;
      setPlayhead(Math.min(Math.max(0, t), maxT));
    },
    [pxPerSecond, setPlayhead, duration, visibleSeconds, setTimelinePlaying],
  );

  const onClipClick = useCallback(
    (e: React.MouseEvent, clipId: string) => {
      e.stopPropagation();
      setSelectedClipId(clipId);
    },
    [setSelectedClipId],
  );

  const setOpError = useCallback((msg: string) => {
    useTimelineStore.setState({ opErrorMessage: msg });
  }, []);

  const applyMoveClip = useCallback(
    async (
      clipId: string,
      nextStart: number,
      destTrackId: string,
      originTrackId: string,
    ) => {
      const args: Record<string, unknown> = {
        clip_id: clipId,
        timeline_start: nextStart,
      };
      if (destTrackId !== originTrackId) {
        args.track_id = destTrackId;
      }
      await applyOperation({ operation: "move_clip", arguments: args });
    },
    [applyOperation],
  );

  /** In-timeline clip move — document capture so listeners run during pointer capture */
  useEffect(() => {
    if (!pointerDrag) return;
    const pd = pointerDrag;

    const onMove = (e: PointerEvent) => {
      if (e.pointerId !== pd.pointerId) return;
      const vp = viewportRef.current;
      if (!vp) return;
      const hit = findTrackUnderPoint(vp, e.clientY);
      if (!hit || hit.trackType !== pd.originTrackType) {
        setDropIndicatorSec(null);
        return;
      }
      const dxSec = (e.clientX - pd.startClientX) / pxPerSecond;
      const nextStart = Math.max(0, snapTimelineSec(pd.originTimelineStart + dxSec));
      setDropIndicatorSec(nextStart);
    };

    const finish = async (e: PointerEvent) => {
      if (e.pointerId !== pd.pointerId) return;
      const vp = viewportRef.current;
      setPointerDrag(null);
      setDropIndicatorSec(null);
      setDragInProgress(false);

      if (!vp) return;
      if (useTimelineStore.getState().applyOperationInProgress) return;

      const hit = findTrackUnderPoint(vp, e.clientY);
      if (!hit || hit.trackType !== pd.originTrackType) {
        setOpError(
          "Move cancelled: drop on a compatible track only (same type as the clip).",
        );
        return;
      }

      const dxSec = (e.clientX - pd.startClientX) / pxPerSecond;
      const nextStart = Math.max(0, snapTimelineSec(pd.originTimelineStart + dxSec));

      const unchanged =
        hit.trackId === pd.originTrackId &&
        Math.abs(nextStart - pd.originTimelineStart) < 1e-6;
      if (unchanged) return;

      try {
        await applyMoveClip(pd.clipId, nextStart, hit.trackId, pd.originTrackId);
      } catch {
        /* store sets opErrorMessage */
      }
    };

    document.addEventListener("pointermove", onMove, { capture: true });
    document.addEventListener("pointerup", finish, { capture: true });
    document.addEventListener("pointercancel", finish, { capture: true });
    return () => {
      document.removeEventListener("pointermove", onMove, { capture: true });
      document.removeEventListener("pointerup", finish, { capture: true });
      document.removeEventListener("pointercancel", finish, { capture: true });
    };
  }, [pointerDrag, pxPerSecond, applyMoveClip, setDragInProgress, setOpError]);

  const onClipPointerDown = useCallback(
    (
      e: React.PointerEvent<HTMLDivElement>,
      opts: {
        clipId: string;
        trackId: string;
        trackType: TrackType;
        timelineStart: number;
      },
    ) => {
      if (e.button !== 0 || busy || applyInProgress) return;
      e.stopPropagation();
      setDragInProgress(true);
      setPointerDrag({
        clipId: opts.clipId,
        originTrackId: opts.trackId,
        originTrackType: opts.trackType,
        pointerId: e.pointerId,
        startClientX: e.clientX,
        originTimelineStart: opts.timelineStart,
      });
      setDropIndicatorSec(opts.timelineStart);
      setSelectedClipId(opts.clipId);
      setTimelinePlaying(false);
    },
    [
      busy,
      applyInProgress,
      setDragInProgress,
      setSelectedClipId,
      setTimelinePlaying,
    ],
  );

  const onLaneDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>, _trackId: string, trackType: TrackType) => {
      if (busy || applyInProgress) return;
      const types = e.dataTransfer?.types ?? [];
      if (!types.includes(FOOTAGE_DRAG_MIME)) return;
      if (trackType === "caption") {
        e.preventDefault();
        e.dataTransfer.dropEffect = "none";
        setDropIndicatorSec(null);
        return;
      }
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      const lane = e.currentTarget;
      const vp = viewportRef.current;
      const xContent = laneContentXFromClient(e.clientX, lane, vp);
      const sec = snapTimelineSec(xContent / pxPerSecond);
      setDropIndicatorSec(sec);
    },
    [busy, applyInProgress, pxPerSecond],
  );

  const onLaneDrop = useCallback(
    async (e: React.DragEvent<HTMLDivElement>, trackId: string, trackType: TrackType) => {
      setDropIndicatorSec(null);
      if (busy || applyInProgress) return;
      const raw = e.dataTransfer.getData(FOOTAGE_DRAG_MIME);
      if (!raw) return;
      e.preventDefault();
      if (trackType === "caption") {
        setOpError("Cannot drop footage on the caption track.");
        return;
      }
      let payload: FootageDragPayload;
      try {
        payload = JSON.parse(raw) as FootageDragPayload;
      } catch {
        setOpError("Invalid footage drag data.");
        return;
      }
      if (!payload.source) {
        setOpError("Footage item has no source path.");
        return;
      }
      const lane = e.currentTarget;
      const vp = viewportRef.current;
      const xContent = laneContentXFromClient(e.clientX, lane, vp);
      const timelineStart = snapTimelineSec(xContent / pxPerSecond);

      const dur =
        typeof payload.duration_seconds === "number" &&
        Number.isFinite(payload.duration_seconds) &&
        payload.duration_seconds > 0
          ? payload.duration_seconds
          : MIN_CLIP_SECONDS;
      const sourceOut = Math.max(MIN_CLIP_SECONDS, dur);

      try {
        await applyOperation({
          operation: "add_clip",
          arguments: {
            track_id: trackId,
            clip: {
              id: crypto.randomUUID(),
              source: payload.source,
              source_in: 0,
              source_out: sourceOut,
              timeline_start: timelineStart,
              created_by: "user",
            },
          },
        });
      } catch {
        /* store */
      }
    },
    [busy, applyInProgress, applyOperation, setOpError],
  );

  const onLaneDragLeave = useCallback(() => {
    setDropIndicatorSec(null);
  }, []);

  useEffect(() => {
    const onDragEnd = () => setDropIndicatorSec(null);
    window.addEventListener("dragend", onDragEnd);
    return () => window.removeEventListener("dragend", onDragEnd);
  }, []);

  useEffect(() => {
    if (!timeline) return;
    const seen = new Set<string>();
    for (const tr of timeline.tracks ?? []) {
      if (tr.type !== "video" && tr.type !== "audio") continue;
      for (const c of tr.clips ?? []) {
        const src = c.source;
        if (src && !seen.has(src)) {
          seen.add(src);
          ensureWaveform(src);
        }
      }
    }
  }, [timeline, ensureWaveform]);

  const playheadLeft = LABEL_WIDTH + playhead * pxPerSecond;
  const indicatorLeft =
    dropIndicatorSec !== null
      ? LABEL_WIDTH + dropIndicatorSec * pxPerSecond
      : null;

  return (
    <div className="lower-workspace timeline-shell">
      <div className="timeline-toolbar" aria-label="Timeline tools">
        <div className="timeline-toolbar__left">
          <span className="timeline-toolbar__plan" title="Current plan file">
            {currentPlanName ? `${currentPlanName}.json` : "—"}
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
          <div className="timeline-toolbar__sep" aria-hidden />
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
        </div>
        <div className="timeline-toolbar__right">
          <span className="timeline-toolbar__stub" title="Not implemented">
            Snap
          </span>
          <span className="timeline-toolbar__stub" title="Not implemented">
            Link
          </span>
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
            {formatTimecode(playhead)}
            {duration > 0 ? ` · ${duration.toFixed(1)}s` : ""}
          </span>
        </div>
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
        {!loading && !error && timeline && totalClipCount === 0 && (
          <p className="timeline-empty-hint panel-message">
            Drag clips from Media onto a video or audio track to start editing.{" "}
            <span className="na-chip" title="CapCut-style empty prompt">
              (Placeholder — not all import flows exist yet.)
            </span>
          </p>
        )}
        {!loading && !error && timeline && (
          <div
            ref={viewportRef}
            className="timeline-viewport"
            onClick={() => setSelectedClipId(null)}
            role="presentation"
          >
            <div
              className="timeline-canvas"
              style={
                {
                  width: totalWidth,
                  minHeight: "100%",
                  "--pps": `${pxPerSecond}px`,
                } as CSSProperties
              }
            >
              <div
                className="timeline-playhead"
                style={{ left: playheadLeft }}
                aria-hidden
              />
              {indicatorLeft !== null && (
                <div
                  aria-hidden
                  style={{
                    position: "absolute",
                    top: RULER_HEIGHT,
                    bottom: 0,
                    left: indicatorLeft,
                    width: 2,
                    marginLeft: -1,
                    background: "rgba(80, 200, 120, 0.95)",
                    zIndex: 4,
                    pointerEvents: "none",
                  }}
                />
              )}

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
                  style={{ width: laneWidth, height: RULER_HEIGHT }}
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
                    style={{ width: laneWidth, height: TRACK_HEIGHT }}
                    data-track-lane-id={track.id}
                    data-track-type={track.type}
                    onDragOver={(e) => onLaneDragOver(e, track.id, track.type)}
                    onDragLeave={onLaneDragLeave}
                    onDrop={(e) => void onLaneDrop(e, track.id, track.type)}
                  >
                    {(track.clips ?? []).map((clip) => {
                      const start = clip.timeline_start;
                      const dur = clipTimelineDuration(clip, track.type);
                      const left = start * pxPerSecond;
                      const width = Math.max(dur * pxPerSecond, 4);
                      const selected = clip.id === selectedClipId;
                      const src = clip.source;
                      const si = clip.source_in ?? 0;
                      const so = clip.source_out ?? si;
                      const sp = clip.speed && clip.speed > 0 ? clip.speed : 1;
                      const showWf =
                        src &&
                        (track.type === "video" || track.type === "audio");
                      return (
                        <div
                          key={clip.id}
                          role="button"
                          tabIndex={0}
                          className={
                            trackClipClass(track.type) +
                            (selected ? " tl-clip--selected" : "")
                          }
                          style={{ left, width, touchAction: "none" }}
                          title={clipDisplayName(clip, track.type)}
                          onClick={(e) => onClipClick(e, clip.id)}
                          onPointerDown={(e) => {
                            onClipPointerDown(e, {
                              clipId: clip.id,
                              trackId: track.id,
                              trackType: track.type,
                              timelineStart: clip.timeline_start,
                            });
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setSelectedClipId(clip.id);
                            }
                          }}
                        >
                          {showWf && (
                            <ClipWaveformCanvas
                              scrollRootRef={viewportRef}
                              source={src}
                              sourceIn={si}
                              sourceOut={so}
                              speed={sp}
                              widthPx={width}
                              heightPx={TRACK_HEIGHT}
                              variant={
                                track.type === "video" ? "video" : "audio"
                              }
                            />
                          )}
                          <span
                            style={{
                              position: "relative",
                              zIndex: 1,
                              pointerEvents: "none",
                            }}
                          >
                            {clipDisplayName(clip, track.type)}
                          </span>
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
