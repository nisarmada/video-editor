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
  copyClipsPayload,
  expandSelectionWithAvLinks,
  findClipById,
  linkedPartnerId,
  selectionIdsForClick,
  orderedTracks,
  playheadInsideClip,
  readClipFromClipboard,
} from "../timeline/selection";
import { getBindingLabel } from "../shortcuts/tooltip";
import { useKeybindingsStore } from "../store/keybindingsStore";
import TimelineContextMenu, {
  type ContextMenuState,
} from "./TimelineContextMenu";
import {
  FOOTAGE_DRAG_MIME,
  FOOTAGE_DRAG_TEXT_TYPE,
  MIN_CLIP_SECONDS,
  TIMELINE_SNAP_SEC,
} from "../timeline/dragConstants";
import {
  laneContentXFromClient,
  findTrackUnderPoint,
  clipAtTimeOnTrack,
  TIMELINE_LABEL_WIDTH,
  TIMELINE_RULER_HEIGHT,
  TIMELINE_TRACK_HEIGHT,
} from "../timeline/timelinePointer";
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
import {
  updateCursorContextPartial,
  resetCursorContext,
  setIgnoreCursorMovesUntil,
  shouldIgnoreCursorPointerMove,
  setCursorHoverClip,
} from "../store/cursorContextStore";
import { timelineViewportElRef, useEditorSettingsStore } from "../store/editorSettingsStore";
import { useTimelineMarquee } from "../hooks/useTimelineMarquee";
import { validateGroupMove } from "../timeline/groupMove";

const LABEL_WIDTH = TIMELINE_LABEL_WIDTH;
const RULER_HEIGHT = TIMELINE_RULER_HEIGHT;
const TRACK_HEIGHT = TIMELINE_TRACK_HEIGHT;

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

type PointerDragMember = {
  clipId: string;
  originTrackId: string;
  originTrackType: TrackType;
  originTimelineStart: number;
};

type PointerDragState = {
  primary: PointerDragMember;
  pointerId: number;
  startClientX: number;
  group: PointerDragMember[];
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
  const moveClipsToPlans = useTimelineStore((s) => s.moveClipsToPlans);
  const runBatchOperationSteps = useTimelineStore((s) => s.runBatchOperationSteps);
  const setClipPropertyBatch = useTimelineStore((s) => s.setClipPropertyBatch);
  const shortcutToast = useTimelineStore((s) => s.shortcutToast);
  const setShortcutToast = useTimelineStore((s) => s.setShortcutToast);

  const rulerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const cursorGuideRef = useRef<HTMLDivElement>(null);
  const cursorMoveRaf = useRef<number | null>(null);
  const ensureWaveform = useWaveformCacheStore((s) => s.ensureFetch);
  const showCursorGuide = useEditorSettingsStore((s) => s.showCursorTimelineGuide);

  /** Pixels available for lanes (viewport minus sticky label); stretches short edits to full width. */
  const [viewportLanePx, setViewportLanePx] = useState(800);

  const [dropIndicatorSec, setDropIndicatorSec] = useState<number | null>(null);
  const [pointerDrag, setPointerDrag] = useState<PointerDragState | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
  /** Clip that would receive cursor-based shortcuts (keyboard), for outline */
  const [cursorTargetClipId, setCursorTargetClipId] = useState<string | null>(null);

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

  const runBatchSeparate = useCallback(
    async (ids: string[]) => {
      if (!timeline) return;
      const steps: { operation: string; arguments: Record<string, unknown> }[] = [];
      let skip = 0;
      for (const id of ids) {
        const h = findClipById(timeline, id);
        if (h?.trackType === "video" && h.clip.audio_source !== "detached") {
          steps.push({ operation: "separate_audio", arguments: { clip_id: id } });
        } else skip += 1;
      }
      if (steps.length === 0) {
        setOpError("No selected clips with embedded audio.");
        return;
      }
      await runBatchOperationSteps(steps);
      if (skip > 0) {
        setShortcutToast(`Separated ${steps.length} of ${ids.length}; ${skip} skipped.`);
      }
    },
    [timeline, runBatchOperationSteps, setOpError, setShortcutToast],
  );

  const runBatchReattach = useCallback(
    async (ids: string[]) => {
      if (!timeline) return;
      const steps: { operation: string; arguments: Record<string, unknown> }[] = [];
      let skip = 0;
      for (const id of ids) {
        const h = findClipById(timeline, id);
        const ok =
          h?.trackType === "video"
            ? h.clip.audio_source === "detached"
            : h?.trackType === "audio" && !!h.clip.group_id;
        if (ok) steps.push({ operation: "reattach_audio", arguments: { clip_id: id } });
        else skip += 1;
      }
      if (steps.length === 0) {
        setOpError("No selected clips that can reattach audio.");
        return;
      }
      await runBatchOperationSteps(steps);
      if (skip > 0) {
        setShortcutToast(`Reattached ${steps.length} of ${ids.length}; ${skip} skipped.`);
      }
    },
    [timeline, runBatchOperationSteps, setOpError, setShortcutToast],
  );

  const runBatchUnlink = useCallback(
    async (ids: string[]) => {
      if (!timeline) return;
      const steps: { operation: string; arguments: Record<string, unknown> }[] = [];
      let skip = 0;
      for (const id of ids) {
        const h = findClipById(timeline, id);
        if (h?.clip.group_id) {
          steps.push({ operation: "unlink_clips", arguments: { clip_id: id } });
        } else skip += 1;
      }
      if (steps.length === 0) {
        setOpError("No linked clips in selection.");
        return;
      }
      await runBatchOperationSteps(steps);
      if (skip > 0) {
        setShortcutToast(`Unlinked ${steps.length} of ${ids.length}; ${skip} skipped.`);
      }
    },
    [timeline, runBatchOperationSteps, setOpError, setShortcutToast],
  );

  const copySelectedClips = useCallback(() => {
    if (!timeline) return;
    const tracks = orderedTracks(timeline);
    const items = selectedClipIds
      .map((id) => {
        const hit = findClipById(timeline, id);
        if (!hit) return null;
        const trackIndex = tracks.findIndex((t) => t.id === hit.trackId);
        return {
          clip: hit.clip,
          sourceTrackId: hit.trackId,
          sourceTrackType: hit.trackType,
          timelineStart: hit.clip.timeline_start,
          trackIndex: trackIndex >= 0 ? trackIndex : 0,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x != null);
    copyClipsPayload(items);
  }, [timeline, selectedClipIds]);

  const linkingEnabled = timeline?.settings?.clip_linking_enabled !== false;
  const selectLinkedTogether = useEditorSettingsStore(
    (s) => s.selectLinkedClipsTogether,
  );
  const setSelectLinkedTogether = useEditorSettingsStore((s) => s.setUi);
  const { marquee, onLanePointerDown } = useTimelineMarquee(
    viewportRef,
    timeline,
    pxPerSecond,
  );
  const selectionCount = selectedClipIds.length;

  const kbOverrides = useKeybindingsStore((s) => s.overrides);
  useEditorSettingsStore((s) => s.shortcutTargeting);
  useEditorSettingsStore((s) => s.perActionTargetMode);
  const bindingTitle = useCallback(
    (actionId: string, label: string) => `${label} (${getBindingLabel(actionId, kbOverrides)})`,
    [kbOverrides],
  );
  const bindingKeysOnly = useCallback(
    (actionId: string) => getBindingLabel(actionId, kbOverrides),
    [kbOverrides],
  );

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

  useLayoutEffect(() => {
    timelineViewportElRef.current = viewportRef.current;
    return () => {
      timelineViewportElRef.current = null;
    };
  }, [loading, error, timeline]);

  useEffect(() => {
    if (!timeline) return;

    const syncFromPointer = (e: PointerEvent) => {
      if (shouldIgnoreCursorPointerMove()) return;
      const vp = viewportRef.current;
      if (!vp) return;
      const vr = vp.getBoundingClientRect();
      if (
        e.clientX < vr.left ||
        e.clientX > vr.right ||
        e.clientY < vr.top ||
        e.clientY > vr.bottom
      ) {
        updateCursorContextPartial({
          region: "none",
          trackIdAtCursor: null,
          trackTypeAtCursor: null,
          clipIdAtCursor: null,
          clipOffsetAtCursor: null,
          timeAtCursorRaw: 0,
        });
        setCursorTargetClipId(null);
        setCursorHoverClip(null);
        if (cursorGuideRef.current) cursorGuideRef.current.style.display = "none";
        return;
      }

      const canvas = vp.querySelector<HTMLElement>(".timeline-canvas");
      if (!canvas) return;
      const cr = canvas.getBoundingClientRect();
      const inCanvas =
        e.clientX >= cr.left &&
        e.clientX <= cr.right &&
        e.clientY >= cr.top &&
        e.clientY <= cr.bottom;
      if (!inCanvas) {
        updateCursorContextPartial({
          region: "none",
          trackIdAtCursor: null,
          trackTypeAtCursor: null,
          clipIdAtCursor: null,
          clipOffsetAtCursor: null,
          timeAtCursorRaw: 0,
        });
        setCursorTargetClipId(null);
        setCursorHoverClip(null);
        if (cursorGuideRef.current) cursorGuideRef.current.style.display = "none";
        return;
      }

      const mq =
        typeof window !== "undefined" ? window.matchMedia("(pointer: coarse)") : null;
      const hasFine = !mq?.matches;
      const relY = e.clientY - cr.top;
      const sub: "ruler" | "timeline" =
        relY < RULER_HEIGHT ? "ruler" : "timeline";

      let yProbe = e.clientY;
      if (sub === "ruler") {
        const firstLane = vp.querySelector<HTMLElement>("[data-track-lane-id]");
        if (firstLane) {
          const lr = firstLane.getBoundingClientRect();
          yProbe = lr.top + Math.min(8, lr.height / 2);
        }
      }

      const trackHit = findTrackUnderPoint(vp, yProbe);
      let trackId: string | null = trackHit?.trackId ?? null;
      let trackType: TrackType | null = trackHit?.trackType ?? null;
      let rawSec = 0;
      let clipId: string | null = null;
      let offsetInClip: number | null = null;

      if (trackHit) {
        const lane = vp.querySelector<HTMLElement>(
          `[data-track-lane-id="${trackHit.trackId}"]`,
        );
        if (lane) {
          const xInLane = laneContentXFromClient(e.clientX, lane, vp);
          rawSec = Math.max(0, xInLane / pxPerSecond);
          const cHit = clipAtTimeOnTrack(timeline, trackHit.trackId, rawSec);
          if (cHit) {
            clipId = cHit.clipId;
            offsetInClip = cHit.offsetInClip;
          }
        }
      }

      updateCursorContextPartial({
        region: sub === "ruler" ? "ruler" : "timeline",
        clientX: e.clientX,
        clientY: e.clientY,
        hasFinePointer: hasFine,
        timeAtCursorRaw: rawSec,
        trackIdAtCursor: trackId,
        trackTypeAtCursor: trackType,
        clipIdAtCursor: clipId,
        clipOffsetAtCursor: offsetInClip,
      });

      setCursorTargetClipId(clipId);
      setCursorHoverClip(clipId);

      const xGuide = e.clientX - cr.left + vp.scrollLeft;
      const gl = cursorGuideRef.current;
      if (gl) {
        gl.style.display =
          showCursorGuide && sub === "timeline" && hasFine ? "block" : "none";
        gl.style.left = `${xGuide}px`;
      }
    };

    const onPointerMove = (e: PointerEvent) => {
      if (cursorMoveRaf.current != null) return;
      cursorMoveRaf.current = window.requestAnimationFrame(() => {
        cursorMoveRaf.current = null;
        syncFromPointer(e);
      });
    };

    const onLeaveWindow = () => {
      resetCursorContext();
      setCursorTargetClipId(null);
      setCursorHoverClip(null);
      if (cursorGuideRef.current) cursorGuideRef.current.style.display = "none";
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("blur", onLeaveWindow);
    document.addEventListener("mouseleave", onLeaveWindow);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("blur", onLeaveWindow);
      document.removeEventListener("mouseleave", onLeaveWindow);
      if (cursorMoveRaf.current != null) {
        cancelAnimationFrame(cursorMoveRaf.current);
        cursorMoveRaf.current = null;
      }
    };
  }, [timeline, pxPerSecond, showCursorGuide]);

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
      const ignoreLinks = e.altKey;
      const linkSelect = !ignoreLinks && selectLinkedTogether;
      const additive = e.shiftKey || e.metaKey || e.ctrlKey;
      if (additive) {
        const cur = new Set(selectedClipIds);
        const toToggle = selectionIdsForClick(timeline, clipId, linkSelect);
        const removing = toToggle.every((id) => cur.has(id));
        for (const id of toToggle) {
          if (removing) cur.delete(id);
          else cur.add(id);
        }
        setSelectedClipIds([...cur], { anchorId: clipId });
      } else {
        const expanded = selectionIdsForClick(timeline, clipId, linkSelect);
        setSelectedClipIds(expanded, { anchorId: clipId });
      }
    },
    [
      timeline,
      selectedClipIds,
      selectLinkedTogether,
      setSelectedClipIds,
    ],
  );

  /** In-timeline clip move — document capture so listeners run during pointer capture */
  useEffect(() => {
    if (!pointerDrag) return;
    const pd = pointerDrag;

    const onMove = (e: PointerEvent) => {
      if (e.pointerId !== pd.pointerId) return;
      const vp = viewportRef.current;
      if (!vp) return;
      const dxSec = (e.clientX - pd.startClientX) / pxPerSecond;
      const nextStart = Math.max(
        0,
        snapTimelineSec(pd.primary.originTimelineStart + dxSec),
      );
      setDropIndicatorSec(nextStart);
    };

    const finish = async (e: PointerEvent) => {
      if (e.pointerId !== pd.pointerId) return;
      const vp = viewportRef.current;
      const tl = useTimelineStore.getState().timeline;
      setPointerDrag(null);
      setIgnoreCursorMovesUntil(0);
      setDropIndicatorSec(null);
      setDragInProgress(false);

      if (!vp || !tl) return;
      if (useTimelineStore.getState().applyOperationInProgress) return;

      const dxSec = (e.clientX - pd.startClientX) / pxPerSecond;
      const delta = snapTimelineSec(pd.primary.originTimelineStart + dxSec) - pd.primary.originTimelineStart;
      if (Math.abs(delta) < 1e-6) return;

      const movingIds = pd.group.map((g) => g.clipId);
      const validation = validateGroupMove(tl, movingIds, delta);
      if (!validation.ok) {
        setOpError(validation.message);
        return;
      }

      try {
        await moveClipsToPlans(validation.moves);
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
  }, [pointerDrag, pxPerSecond, moveClipsToPlans, setDragInProgress, setOpError]);

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
      const tr = timeline?.tracks?.find((x) => x.id === opts.trackId);
      if (tr?.locked) return;
      e.stopPropagation();
      setDragInProgress(true);
      setIgnoreCursorMovesUntil(performance.now() + 60_000);
      const st = useTimelineStore.getState();
      const sel = st.selectedClipIds;
      const inSel = sel.includes(opts.clipId);
      let group: PointerDragMember[] = [];
      if (inSel && sel.length > 1 && timeline) {
        for (const id of sel) {
          const hit = findClipById(timeline, id);
          if (!hit) continue;
          group.push({
            clipId: id,
            originTrackId: hit.trackId,
            originTrackType: hit.trackType as TrackType,
            originTimelineStart: hit.clip.timeline_start,
          });
        }
      }
      if (group.length === 0) {
        group = [
          {
            clipId: opts.clipId,
            originTrackId: opts.trackId,
            originTrackType: opts.trackType,
            originTimelineStart: opts.timelineStart,
          },
        ];
      }
      const primary = group.find((g) => g.clipId === opts.clipId) ?? group[0]!;
      setPointerDrag({
        primary,
        group,
        pointerId: e.pointerId,
        startClientX: e.clientX,
      });
      setDropIndicatorSec(primary.originTimelineStart);
      const tl = st.timeline;
      if (!inSel && tl) {
        setSelectedClipIds(
          selectionIdsForClick(tl, opts.clipId, selectLinkedTogether),
          { anchorId: opts.clipId },
        );
      }
      setTimelinePlaying(false);
    },
    [
      busy,
      applyInProgress,
      timeline,
      selectLinkedTogether,
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

  const toggleTrackLocked = useCallback(
    (trackId: string, current: boolean | undefined) => {
      void runOp(() =>
        applyOperation({
          operation: "set_track_property",
          arguments: {
            track_id: trackId,
            properties: { locked: !current },
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
            title={bindingTitle("undo", "Undo")}
          >
            Undo
          </button>
          <button
            type="button"
            className="timeline-toolbar__tool timeline-toolbar__tool--text"
            disabled={busy || !canRedo}
            onClick={() => void redo()}
            title={bindingTitle("redo", "Redo")}
          >
            Redo
          </button>
          <div className="timeline-toolbar__sep" aria-hidden />
          {selectionCount > 0 ? (
            <span className="timeline-toolbar__selection-badge" title="Selected clips">
              {selectionCount} selected
            </span>
          ) : null}
          <button
            type="button"
            className="timeline-toolbar__tool timeline-toolbar__tool--text"
            disabled={busy || selectionCount === 0}
            onClick={() => void splitAtPlayhead().catch(() => {})}
            title={bindingTitle("split", "Split")}
          >
            Split
          </button>
          <button
            type="button"
            className="timeline-toolbar__tool timeline-toolbar__tool--text"
            disabled={busy || selectionCount === 0}
            onClick={() => void deleteSelectedClip().catch(() => {})}
            title={bindingTitle("delete", "Delete")}
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
            title={bindingTitle("toggle_clip_linking", "Toggle clip linking")}
            onClick={() => void runOp(() => toggleClipLinking())}
          >
            Link {linkingEnabled ? "on" : "off"}
          </button>
          <button
            type="button"
            className={
              "timeline-toolbar__tool timeline-toolbar__tool--text" +
              (selectLinkedTogether ? " timeline-toolbar__link-on" : "")
            }
            disabled={busy}
            title="Select separated audio+video together when clicking (Alt+click = one clip)"
            onClick={() =>
              setSelectLinkedTogether({
                selectLinkedClipsTogether: !selectLinkedTogether,
              })
            }
          >
            Select linked {selectLinkedTogether ? "on" : "off"}
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
      {shortcutToast && (
        <div className="timeline-shortcut-toast" role="status">
          {shortcutToast}
          <button
            type="button"
            className="link-btn"
            onClick={() => setShortcutToast(null)}
          >
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
              <div
                ref={cursorGuideRef}
                className="timeline-cursor-guide"
                aria-hidden
                style={{ display: "none", left: 0 }}
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
              {marquee.active && marquee.rect ? (
                <div
                  className="timeline-marquee-rect"
                  aria-hidden
                  style={{
                    left: marquee.rect.left,
                    top: marquee.rect.top,
                    width: marquee.rect.right - marquee.rect.left,
                    height: marquee.rect.bottom - marquee.rect.top,
                  }}
                />
              ) : null}

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
                      {track.type === "caption" &&
                      (track.clips?.length ?? 0) === 0 ? (
                        <p className="track-label__caption-hint">
                          Speech captions are generated from the transcript on export
                          (Captions tab). Editable caption clips appear here when the
                          plan includes a caption track.
                        </p>
                      ) : null}
                      {showTrackControls ? (
                        <div className="track-label__row">
                          <button
                            type="button"
                            className={
                              "track-mute-btn" +
                              (track.muted ? " track-mute-btn--on" : "")
                            }
                            title={bindingTitle("toggle_track_mute", "Mute track")}
                            aria-label={
                              track.muted ? "Unmute track" : "Mute track"
                            }
                            disabled={busy || track.locked}
                            onClick={() =>
                              toggleTrackMuted(track.id, track.muted)
                            }
                          >
                            {track.muted ? "🔇" : "🔊"}
                          </button>
                          <button
                            type="button"
                            className={
                              "track-lock-btn" + (track.locked ? " track-lock-btn--on" : "")
                            }
                            title={bindingTitle("toggle_track_lock", "Lock track")}
                            aria-label={track.locked ? "Unlock track" : "Lock track"}
                            disabled={busy}
                            onClick={() =>
                              toggleTrackLocked(track.id, track.locked)
                            }
                          >
                            {track.locked ? "🔒" : "🔓"}
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
                      onPointerDown={onLanePointerDown}
                    >
                      {(track.clips ?? []).map((clip) => {
                        const start = clip.timeline_start;
                        const dur = clipTimelineDuration(clip, track.type);
                        const left = start * pxPerSecond;
                        const width = Math.max(dur * pxPerSecond, 4);
                        const selected =
                          selectedClipIds.includes(clip.id) ||
                          clip.id === selectedClipId;
                        const cursorTarget = clip.id === cursorTargetClipId;
                        const partner =
                          timeline ? linkedPartnerId(timeline, clip.id) : null;
                        const linked = !!partner;
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
                              (cursorTarget ? " tl-clip--cursor-target" : "")
                            }
                            style={{ left, width, touchAction: "none" }}
                            title={clipDisplayName(clip, track.type)}
                            onClick={(e) => onClipClick(e, clip.id)}
                            onContextMenu={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              const sel = useTimelineStore.getState().selectedClipIds;
                              if (!sel.includes(clip.id)) {
                                setSelectedClipIds(
                                  selectionIdsForClick(
                                    timeline,
                                    clip.id,
                                    selectLinkedTogether,
                                  ),
                                  { anchorId: clip.id },
                                );
                              }
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
                const nSel = selectedClipIds.length;
                const suffix = nSel > 1 ? ` (${nSel})` : "";
                return [
                  {
                    label: `Separate audio${suffix}`,
                    shortcut: bindingKeysOnly("separate_audio"),
                    disabled: !canSeparate || busy,
                    onSelect: () => void runOp(() => runBatchSeparate(selectedClipIds)),
                  },
                  {
                    label: `Reattach audio${suffix}`,
                    shortcut: bindingKeysOnly("reattach_audio"),
                    disabled: !canReattach || busy,
                    onSelect: () => void runOp(() => runBatchReattach(selectedClipIds)),
                  },
                  {
                    label: `Unlink${suffix}`,
                    shortcut: bindingKeysOnly("unlink_clips"),
                    disabled: busy || (nSel <= 1 && !canUnlink),
                    onSelect: () => void runOp(() => runBatchUnlink(selectedClipIds)),
                  },
                  {
                    label: `Split at playhead${suffix}`,
                    shortcut: bindingKeysOnly("split"),
                    disabled: busy || (nSel <= 1 && !playheadInsideClip(c, trackType, playhead)),
                    onSelect: () => void runOp(() => splitAtPlayhead()),
                  },
                  {
                    label: `Delete${suffix}`,
                    shortcut: bindingKeysOnly("delete"),
                    disabled: busy || nSel === 0,
                    onSelect: () => void runOp(() => deleteSelectedClip()),
                  },
                  {
                    label: (vol <= 0 ? "Unmute clip" : "Mute clip") + suffix,
                    shortcut: bindingKeysOnly("mute_clip"),
                    disabled: busy || nSel === 0,
                    onSelect: () =>
                      void runOp(async () => {
                        const steps = selectedClipIds.map((id) => {
                          const h = findClipById(timeline!, id);
                          const v = h?.clip.volume !== undefined ? h.clip.volume : 1;
                          return {
                            operation: "set_clip_property",
                            arguments: {
                              clip_id: id,
                              properties: { volume: v <= 0 ? 1 : 0 },
                            },
                          };
                        });
                        await runBatchOperationSteps(steps);
                      }),
                  },
                  {
                    label: `Copy${suffix}`,
                    shortcut: bindingKeysOnly("copy_clip"),
                    disabled: busy || nSel === 0,
                    onSelect: () => copySelectedClips(),
                  },
                  {
                    label: "Paste at playhead",
                    shortcut: bindingKeysOnly("paste_clip"),
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
