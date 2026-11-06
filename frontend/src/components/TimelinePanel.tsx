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
  clipLinkingEnabled,
  copyClipPayload,
  expandLinkedSelection,
  findClipById,
  linkedPartnerId,
  orderedTracks,
  playheadInsideClip,
  readClipFromClipboard,
} from "../timeline/selection";
import { shortcutKeys, shortcutTitle } from "../timeline/shortcuts";
import TimelineContextMenu, {
  type ContextMenuState,
} from "./TimelineContextMenu";
import {
  FOOTAGE_DRAG_MIME,
  FOOTAGE_DRAG_TEXT_TYPE,
  MIN_CLIP_SECONDS,
  TIMELINE_SNAP_SEC,
} from "../timeline/dragConstants";
import { isFootageFromBinDragging } from "../timeline/footageDragState";
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

function readFootageDragPayload(e: React.DragEvent): FootageDragPayload | null {
  let raw = e.dataTransfer.getData(FOOTAGE_DRAG_MIME);
  if (!raw) {
    raw = e.dataTransfer.getData(FOOTAGE_DRAG_TEXT_TYPE);
  }
  if (!raw) return null;
  try {
    return JSON.parse(raw) as FootageDragPayload;
  } catch {
    return null;
  }
}

function isFootageBinDrag(e: React.DragEvent): boolean {
  const dt = e.dataTransfer;
  if (!dt) return false;
  const t = dt.types ?? [];
  if (t.includes(FOOTAGE_DRAG_MIME) || t.includes(FOOTAGE_DRAG_TEXT_TYPE)) {
    return true;
  }
  return isFootageFromBinDragging();
}

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
  const selectedClipIds = useTimelineStore((s) => s.selectedClipIds);
  const setSelectedClipId = useTimelineStore((s) => s.setSelectedClipId);
  const setSelectedClipIds = useTimelineStore((s) => s.setSelectedClipIds);
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
  const separateAudio = useTimelineStore((s) => s.separateAudio);
  const reattachAudio = useTimelineStore((s) => s.reattachAudio);
  const unlinkClipsAction = useTimelineStore((s) => s.unlinkClipsAction);
  const toggleClipLinking = useTimelineStore((s) => s.toggleClipLinking);
  const applyOperation = useTimelineStore((s) => s.applyOperation);

  const rulerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const ensureWaveform = useWaveformCacheStore((s) => s.ensureFetch);

  /** Pixels available for lanes (viewport minus sticky label); stretches short edits to full width. */
  const [viewportLanePx, setViewportLanePx] = useState(800);

  const [dropIndicatorSec, setDropIndicatorSec] = useState<number | null>(null);
  const [pointerDrag, setPointerDrag] = useState<PointerDragState | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
  const [hoverClipId, setHoverClipId] = useState<string | null>(null);

  const canUndo = undoStack.length > 0;
  const canRedo = redoStack.length > 0;
  const busy = !canMutateTimeline({
    applyOperationInProgress: applyInProgress,
    dragInProgress,
  });

  const setOpError = useCallback((msg: string) => {
    useTimelineStore.setState({ opErrorMessage: msg });
  }, []);

  const runOp = useCallback(async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch {
      /* store sets opErrorMessage */
    }
  }, []);

  const linkingEnabled = timeline?.settings?.clip_linking_enabled !== false;

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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
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
      if (busy) return;

      const isMod = e.metaKey || e.ctrlKey;
      if (isMod && e.shiftKey && e.code === "KeyS") {
        e.preventDefault();
        void runOp(() => useTimelineStore.getState().separateAudio());
        return;
      }
      if (isMod && !e.shiftKey && e.code === "KeyL") {
        e.preventDefault();
        void runOp(() => useTimelineStore.getState().toggleClipLinking());
        return;
      }
      if (!isMod && e.code === "KeyM") {
        e.preventDefault();
        void runOp(() => useTimelineStore.getState().toggleSelectedTrackMute());
        return;
      }
      if (isMod && e.code === "KeyC" && useTimelineStore.getState().selectedClipId) {
        e.preventDefault();
        const tl = useTimelineStore.getState().timeline;
        const sid = useTimelineStore.getState().selectedClipId;
        if (!tl || !sid) return;
        const hit = findClipById(tl, sid);
        if (hit) {
          copyClipPayload({
            clip: hit.clip,
            sourceTrackId: hit.trackId,
            sourceTrackType: hit.trackType,
          });
        }
        return;
      }
      if (isMod && e.code === "KeyV") {
        e.preventDefault();
        const tl = useTimelineStore.getState().timeline;
        const ph = useTimelineStore.getState().playheadSeconds;
        const data = readClipFromClipboard();
        if (!tl || !data) return;
        const videoTr = tl.tracks.find((x) => x.type === "video");
        const audioTr = tl.tracks.find((x) => x.type === "audio");
        const capTr = tl.tracks.find((x) => x.type === "caption");
        const st = data.sourceTrackType;
        const targetId =
          st === "audio" && audioTr
            ? audioTr.id
            : st === "caption" && capTr
              ? capTr.id
              : videoTr?.id;
        const { group_id: _omitG, id: _omitId, ...clipRest } = data.clip;
        const newClip: Record<string, unknown> = {
          ...clipRest,
          id: crypto.randomUUID(),
          timeline_start: ph,
          created_by: "user",
        };
        if (st === "video" || (!st && !targetId)) {
          newClip.audio_source = "embedded";
        }
        const args: Record<string, unknown> = { clip: newClip };
        if (targetId) args.track_id = targetId;
        void runOp(() =>
          useTimelineStore.getState().applyOperation({
            operation: "add_clip",
            arguments: args,
          }),
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, runOp]);

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
      if (!timeline) return;
      if (e.shiftKey) {
        const cur = new Set(selectedClipIds);
        if (cur.has(clipId)) cur.delete(clipId);
        else cur.add(clipId);
        let next = [...cur];
        if (clipLinkingEnabled(timeline)) {
          next = expandLinkedSelection(timeline, next);
        }
        setSelectedClipIds(next);
      } else {
        if (clipLinkingEnabled(timeline)) {
          const expanded = expandLinkedSelection(timeline, [clipId]);
          setSelectedClipIds(expanded);
        } else {
          setSelectedClipId(clipId);
        }
      }
    },
    [
      timeline,
      selectedClipIds,
      setSelectedClipId,
      setSelectedClipIds,
    ],
  );

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
      const tl = useTimelineStore.getState().timeline;
      if (tl && clipLinkingEnabled(tl)) {
        setSelectedClipIds(expandLinkedSelection(tl, [opts.clipId]));
      } else {
        setSelectedClipId(opts.clipId);
      }
      setTimelinePlaying(false);
    },
    [
      busy,
      applyInProgress,
      setDragInProgress,
      setSelectedClipId,
      setSelectedClipIds,
      setTimelinePlaying,
    ],
  );

  const timelineSecFromDragClientX = useCallback(
    (clientX: number, laneEl: HTMLElement | null) => {
      const vp = viewportRef.current;
      if (!vp) return 0;
      let xContent: number;
      if (laneEl) {
        xContent = laneContentXFromClient(clientX, laneEl, vp);
      } else {
        const canvas = vp.querySelector<HTMLElement>(".timeline-canvas");
        if (!canvas) return 0;
        const rect = canvas.getBoundingClientRect();
        xContent = Math.max(0, clientX - rect.left - LABEL_WIDTH + vp.scrollLeft);
      }
      const sec = xContent / pxPerSecond;
      if (!Number.isFinite(sec)) return 0;
      return snapTimelineSec(sec);
    },
    [pxPerSecond],
  );

  const dropFootageAtTimelineSec = useCallback(
    async (
      e: React.DragEvent,
      payload: FootageDragPayload,
      opts: { trackId?: string; trackType: TrackType } | null,
      laneEl: HTMLElement | null,
    ) => {
      setDropIndicatorSec(null);
      e.preventDefault();
      if (busy || applyInProgress) return;
      if (!payload.source) {
        setOpError("Footage item has no source path.");
        return;
      }
      const trackType = opts?.trackType;
      if (trackType === "caption") {
        setOpError("Cannot drop footage on the caption track.");
        return;
      }
      const timelineStart = timelineSecFromDragClientX(e.clientX, laneEl);

      const dur =
        typeof payload.duration_seconds === "number" &&
        Number.isFinite(payload.duration_seconds) &&
        payload.duration_seconds > 0
          ? payload.duration_seconds
          : MIN_CLIP_SECONDS;
      const sourceOut = Math.max(MIN_CLIP_SECONDS, dur);

      const clip: Record<string, unknown> = {
        id: crypto.randomUUID(),
        source: payload.source,
        source_in: 0,
        source_out: sourceOut,
        timeline_start: timelineStart,
        created_by: "user",
      };
      if (!trackType || trackType === "video") {
        clip.audio_source = "embedded";
      }

      const args: Record<string, unknown> = { clip };
      if (opts?.trackId) {
        args.track_id = opts.trackId;
      }
      try {
        await applyOperation({
          operation: "add_clip",
          arguments: args,
        });
      } catch {
        /* store sets opErrorMessage */
      }
    },
    [
      applyOperation,
      busy,
      applyInProgress,
      setOpError,
      timelineSecFromDragClientX,
    ],
  );

  const onLaneDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>, _trackId: string, trackType: TrackType) => {
      if (busy || applyInProgress) return;
      if (!isFootageBinDrag(e)) return;
      if (trackType === "caption") {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "none";
        setDropIndicatorSec(null);
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "copy";
      const lane = e.currentTarget;
      const sec = timelineSecFromDragClientX(e.clientX, lane);
      setDropIndicatorSec(sec);
    },
    [busy, applyInProgress, timelineSecFromDragClientX],
  );

  const onLaneDrop = useCallback(
    async (e: React.DragEvent<HTMLDivElement>, trackId: string, trackType: TrackType) => {
      if (isFootageBinDrag(e)) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (busy || applyInProgress) return;
      const payload = readFootageDragPayload(e);
      if (!payload) {
        setOpError("Missing footage drag data (try again).");
        return;
      }
      await dropFootageAtTimelineSec(e, payload, { trackId, trackType }, e.currentTarget);
    },
    [busy, applyInProgress, dropFootageAtTimelineSec, setOpError],
  );

  /** Drops on ruler / padded canvas (not on a track lane — those handle locally). */
  const onCanvasFootageDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (busy || applyInProgress) return;
      if (!isFootageBinDrag(e)) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "copy";
      const vp = viewportRef.current;
      const hit = vp && findTrackUnderPoint(vp, e.clientY);
      const sec = timelineSecFromDragClientX(e.clientX, null);
      if (hit?.trackType === "caption") {
        e.dataTransfer.dropEffect = "none";
        setDropIndicatorSec(null);
        return;
      }
      setDropIndicatorSec(sec);
    },
    [busy, applyInProgress, timelineSecFromDragClientX],
  );

  const onCanvasFootageDrop = useCallback(
    async (e: React.DragEvent<HTMLDivElement>) => {
      if (isFootageBinDrag(e)) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (busy || applyInProgress) return;
      const payload = readFootageDragPayload(e);
      if (!payload) {
        setOpError("Missing footage drag data (try again).");
        return;
      }
      const vp = viewportRef.current;
      const hit = vp ? findTrackUnderPoint(vp, e.clientY) : null;
      await dropFootageAtTimelineSec(
        e,
        payload,
        hit ? { trackId: hit.trackId, trackType: hit.trackType } : null,
        null,
      );
    },
    [busy, applyInProgress, dropFootageAtTimelineSec, setOpError],
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

  const trackRows = useMemo(
    () => (timeline ? orderedTracks(timeline) : []),
    [timeline],
  );

  const setTrackVolume = useCallback(
    (trackId: string, vol: number) => {
      void runOp(() =>
        applyOperation({
          operation: "set_track_property",
          arguments: {
            track_id: trackId,
            properties: { volume: Math.max(0, Math.min(2, vol)) },
          },
        }),
      );
    },
    [applyOperation, runOp],
  );

  const toggleTrackMuted = useCallback(
    (trackId: string, current: boolean | undefined) => {
      void runOp(() =>
        applyOperation({
          operation: "set_track_property",
          arguments: {
            track_id: trackId,
            properties: { muted: !current },
          },
        }),
      );
    },
    [applyOperation, runOp],
  );

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
            title={shortcutTitle("undo")}
          >
            Undo
          </button>
          <button
            type="button"
            className="timeline-toolbar__tool timeline-toolbar__tool--text"
            disabled={busy || !canRedo}
            onClick={() => void redo()}
            title={shortcutTitle("redo")}
          >
            Redo
          </button>
          <div className="timeline-toolbar__sep" aria-hidden />
          <button
            type="button"
            className="timeline-toolbar__tool timeline-toolbar__tool--text"
            disabled={busy || !selectedClipId}
            onClick={() => void splitAtPlayhead().catch(() => {})}
            title={shortcutTitle("split")}
          >
            Split
          </button>
          <button
            type="button"
            className="timeline-toolbar__tool timeline-toolbar__tool--text"
            disabled={busy || !selectedClipId}
            onClick={() => void deleteSelectedClip().catch(() => {})}
            title={shortcutTitle("delete")}
          >
            Del
          </button>
        </div>
        <div className="timeline-toolbar__right">
          <span className="timeline-toolbar__stub" title="Not implemented">
            Snap
          </span>
          <button
            type="button"
            className={
              "timeline-toolbar__tool timeline-toolbar__tool--text" +
              (linkingEnabled ? " timeline-toolbar__link-on" : "")
            }
            disabled={busy}
            title={shortcutTitle("toggleLinking")}
            onClick={() => void runOp(() => toggleClipLinking())}
          >
            Link {linkingEnabled ? "on" : "off"}
          </button>
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
            onClick={() => {
              setSelectedClipIds([]);
            }}
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
              onDragOver={onCanvasFootageDragOver}
              onDrop={(e) => void onCanvasFootageDrop(e)}
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

              {trackRows.map((track) => {
                const showTrackControls =
                  track.type === "video" || track.type === "audio";
                const tv = track.volume ?? 1;
                return (
                  <div className="track-row" key={track.id}>
                    <div
                      className={
                        "track-label track-label--sticky track-label--with-controls" +
                        (showTrackControls ? "" : "")
                      }
                      style={{ width: LABEL_WIDTH }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <span className="track-label__title">
                        {track.label ?? track.type}
                      </span>
                      {showTrackControls ? (
                        <div className="track-label__row">
                          <button
                            type="button"
                            className={
                              "track-mute-btn" +
                              (track.muted ? " track-mute-btn--on" : "")
                            }
                            title={shortcutTitle("muteTrack")}
                            aria-label={
                              track.muted ? "Unmute track" : "Mute track"
                            }
                            disabled={busy}
                            onClick={() =>
                              toggleTrackMuted(track.id, track.muted)
                            }
                          >
                            {track.muted ? "🔇" : "🔊"}
                          </button>
                          <label className="track-label__vol">
                            <span className="sr-only">Track volume</span>
                            <input
                              type="range"
                              min={0}
                              max={2}
                              step={0.05}
                              value={tv}
                              disabled={busy}
                              title="Track volume (0–2×)"
                              aria-label={`${track.label ?? track.type} volume`}
                              onChange={(e) =>
                                setTrackVolume(
                                  track.id,
                                  Number(e.target.value),
                                )
                              }
                            />
                          </label>
                        </div>
                      ) : null}
                    </div>
                    <div
                      className="track-lane track-lane--timeline"
                      style={{ width: laneWidth, height: TRACK_HEIGHT }}
                      data-track-lane-id={track.id}
                      data-track-type={track.type}
                      onDragOver={(e) =>
                        onLaneDragOver(e, track.id, track.type)
                      }
                      onDragLeave={onLaneDragLeave}
                      onDrop={(e) => void onLaneDrop(e, track.id, track.type)}
                    >
                      {(track.clips ?? []).map((clip) => {
                        const start = clip.timeline_start;
                        const dur = clipTimelineDuration(clip, track.type);
                        const left = start * pxPerSecond;
                        const width = Math.max(dur * pxPerSecond, 4);
                        const selected =
                          selectedClipIds.includes(clip.id) ||
                          clip.id === selectedClipId;
                        const partner =
                          timeline && (track.type === "video" || track.type === "audio")
                            ? linkedPartnerId(timeline, clip.id)
                            : null;
                        const linked = !!(clip.group_id && partner);
                        const linkedHover =
                          linked &&
                          hoverClipId !== null &&
                          (clip.id === hoverClipId || partner === hoverClipId);
                        const src = clip.source;
                        const si = clip.source_in ?? 0;
                        const so = clip.source_out ?? si;
                        const sp = clip.speed && clip.speed > 0 ? clip.speed : 1;
                        const showWf =
                          src &&
                          (track.type === "video" || track.type === "audio");
                        const detachedVid =
                          track.type === "video" &&
                          clip.audio_source === "detached";
                        return (
                          <div
                            key={clip.id}
                            role="button"
                            tabIndex={0}
                            className={
                              trackClipClass(track.type) +
                              (selected ? " tl-clip--selected" : "") +
                              (linkedHover ? " tl-clip--linked-peer-hover" : "")
                            }
                            style={{ left, width, touchAction: "none" }}
                            title={clipDisplayName(clip, track.type)}
                            onClick={(e) => onClipClick(e, clip.id)}
                            onMouseEnter={() => setHoverClipId(clip.id)}
                            onMouseLeave={() => setHoverClipId(null)}
                            onContextMenu={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              setContextMenu({
                                x: e.clientX,
                                y: e.clientY,
                                clipId: clip.id,
                                trackId: track.id,
                                trackType: track.type,
                              });
                            }}
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
                                if (!timeline) return;
                                const syn = new KeyboardEvent("keydown", {
                                  shiftKey: e.shiftKey,
                                });
                                onClipClick(
                                  syn as unknown as React.MouseEvent,
                                  clip.id,
                                );
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
                              className="tl-clip__row"
                              style={{
                                position: "relative",
                                zIndex: 1,
                                pointerEvents: "none",
                              }}
                            >
                              {linked ? (
                                <span className="tl-clip__link" title="Linked">
                                  🔗
                                </span>
                              ) : null}
                              {detachedVid ? (
                                <span className="tl-clip__badge">No audio</span>
                              ) : null}
                              <span className="tl-clip__name">
                                {clipDisplayName(clip, track.type)}
                              </span>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <TimelineContextMenu
        state={contextMenu}
        onClose={() => setContextMenu(null)}
        items={
          contextMenu && timeline
            ? (() => {
                const hit = findClipById(timeline, contextMenu.clipId);
                if (!hit) return [];
                const { clip, trackType } = hit;
                const c = clip;
                const canSeparate =
                  trackType === "video" && c.audio_source !== "detached";
                const canReattach =
                  (trackType === "video" && c.audio_source === "detached") ||
                  (trackType === "audio" &&
                    !!c.group_id &&
                    timeline.tracks.some((tr) =>
                      (tr.clips ?? []).some(
                        (x) =>
                          x.group_id === c.group_id &&
                          x.audio_source === "detached",
                      ),
                    ));
                const canUnlink = !!c.group_id;
                const vol = c.volume !== undefined ? c.volume : 1;
                const canPaste = !!readClipFromClipboard();
                return [
                  {
                    label: "Separate audio",
                    shortcut: shortcutKeys("separateAudio"),
                    disabled: !canSeparate || busy,
                    onSelect: () =>
                      void runOp(async () => {
                        useTimelineStore.setState({
                          selectedClipId: c.id,
                          selectedClipIds: [c.id],
                        });
                        await separateAudio();
                      }),
                  },
                  {
                    label: "Reattach audio",
                    shortcut: shortcutKeys("reattachAudio"),
                    disabled: !canReattach || busy,
                    onSelect: () =>
                      void runOp(async () => {
                        useTimelineStore.setState({
                          selectedClipId: c.id,
                          selectedClipIds: [c.id],
                        });
                        await reattachAudio();
                      }),
                  },
                  {
                    label: "Unlink",
                    shortcut: shortcutKeys("unlink"),
                    disabled: !canUnlink || busy,
                    onSelect: () =>
                      void runOp(async () => {
                        useTimelineStore.setState({
                          selectedClipId: c.id,
                          selectedClipIds: [c.id],
                        });
                        await unlinkClipsAction();
                      }),
                  },
                  {
                    label: "Split at playhead",
                    shortcut: shortcutKeys("split"),
                    disabled:
                      busy ||
                      !playheadInsideClip(c, trackType, playhead),
                    onSelect: () =>
                      void runOp(async () => {
                        useTimelineStore.setState({
                          selectedClipId: c.id,
                          selectedClipIds: [c.id],
                        });
                        await splitAtPlayhead();
                      }),
                  },
                  {
                    label: "Delete",
                    shortcut: shortcutKeys("delete"),
                    disabled: busy,
                    onSelect: () =>
                      void runOp(async () => {
                        useTimelineStore.setState({
                          selectedClipId: c.id,
                          selectedClipIds: [c.id],
                        });
                        await deleteSelectedClip();
                      }),
                  },
                  {
                    label: vol <= 0 ? "Unmute clip" : "Mute clip",
                    shortcut: shortcutKeys("muteClip"),
                    disabled: busy,
                    onSelect: () =>
                      void runOp(() =>
                        applyOperation({
                          operation: "set_clip_property",
                          arguments: {
                            clip_id: c.id,
                            properties: { volume: vol <= 0 ? 1 : 0 },
                          },
                        }),
                      ),
                  },
                  {
                    label: "Copy",
                    shortcut: shortcutKeys("copyClip"),
                    disabled: busy,
                    onSelect: () =>
                      copyClipPayload({
                        clip: c,
                        sourceTrackId: contextMenu.trackId,
                        sourceTrackType: contextMenu.trackType,
                      }),
                  },
                  {
                    label: "Paste at playhead",
                    shortcut: shortcutKeys("pasteClip"),
                    disabled: busy || !canPaste,
                    onSelect: () => {
                      const data = readClipFromClipboard();
                      if (!data || !timeline) return;
                      const videoTr = timeline.tracks.find(
                        (x) => x.type === "video",
                      );
                      const audioTr = timeline.tracks.find(
                        (x) => x.type === "audio",
                      );
                      const capTr = timeline.tracks.find(
                        (x) => x.type === "caption",
                      );
                      const st = data.sourceTrackType;
                      const targetId =
                        st === "audio" && audioTr
                          ? audioTr.id
                          : st === "caption" && capTr
                            ? capTr.id
                            : videoTr?.id;
                      const { group_id: _g, id: _i, ...rest } = data.clip;
                      const newClip: Record<string, unknown> = {
                        ...rest,
                        id: crypto.randomUUID(),
                        timeline_start: playhead,
                        created_by: "user",
                      };
                      if (st === "video" || (!st && !targetId)) {
                        newClip.audio_source = "embedded";
                      }
                      const args: Record<string, unknown> = { clip: newClip };
                      if (targetId) args.track_id = targetId;
                      void runOp(() =>
                        applyOperation({
                          operation: "add_clip",
                          arguments: args,
                        }),
                      );
                    },
                  },
                ];
              })()
            : []
        }
      />
    </div>
  );
}
