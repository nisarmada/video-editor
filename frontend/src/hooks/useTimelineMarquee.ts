import { useCallback, useEffect, useRef, useState } from "react";
import { useEditorSettingsStore } from "../store/editorSettingsStore";
import { useTimelineStore } from "../store/timelineStore";
import {
  buildClipLayoutRects,
  clientToCanvasContent,
  clipsInMarqueeRect,
  normalizeMarquee,
  type ContentRect,
} from "../timeline/marqueeHitTest";

const DRAG_THRESHOLD_PX = 4;
const EDGE_SCROLL_PX = 28;
const SCROLL_STEP = 14;

export type MarqueeUiState = {
  active: boolean;
  rect: ContentRect | null;
};

type MarqueeSession = {
  pointerId: number;
  additive: boolean;
  startX: number;
  startY: number;
  baseSelection: string[];
};

export function useTimelineMarquee(
  viewportRef: React.RefObject<HTMLDivElement | null>,
  timeline: import("../timeline/types").TimelineV2 | null,
  pxPerSecond: number,
): {
  marquee: MarqueeUiState;
  onLanePointerDown: (e: React.PointerEvent) => void;
} {
  const marqueeMode = useEditorSettingsStore((s) => s.marqueeOverlapMode);
  const setSelectedClipIds = useTimelineStore((s) => s.setSelectedClipIds);
  const sessionRef = useRef<MarqueeSession | null>(null);
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const [marquee, setMarquee] = useState<MarqueeUiState>({ active: false, rect: null });

  const cancelMarquee = useCallback(() => {
    sessionRef.current = null;
    setMarquee({ active: false, rect: null });
    setSessionEpoch((n) => n + 1);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && sessionRef.current) {
        e.preventDefault();
        cancelMarquee();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancelMarquee]);

  useEffect(() => {
    const sess = sessionRef.current;
    if (!sess || !timeline || sessionEpoch === 0) return;

    const vp = viewportRef.current;
    const canvas = vp?.querySelector<HTMLElement>(".timeline-canvas");
    if (!vp || !canvas) return;

    const onMove = (e: PointerEvent) => {
      if (e.pointerId !== sess.pointerId) return;
      const dx = e.clientX - sess.startX;
      const dy = e.clientY - sess.startY;
      if (!marquee.active && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;

      const rect = canvas.getBoundingClientRect();
      const a = clientToCanvasContent(sess.startX, sess.startY, rect, vp.scrollLeft, vp.scrollTop);
      const b = clientToCanvasContent(e.clientX, e.clientY, rect, vp.scrollLeft, vp.scrollTop);
      const box = normalizeMarquee(a.x, a.y, b.x, b.y);
      setMarquee({ active: true, rect: box });

      const layout = buildClipLayoutRects(timeline, pxPerSecond);
      const hits = clipsInMarqueeRect(layout, box, marqueeMode);
      const merged = sess.additive
        ? [...new Set([...sess.baseSelection, ...hits])]
        : hits;
      setSelectedClipIds(merged);

      const vpRect = vp.getBoundingClientRect();
      if (e.clientX < vpRect.left + EDGE_SCROLL_PX) {
        vp.scrollLeft = Math.max(0, vp.scrollLeft - SCROLL_STEP);
      } else if (e.clientX > vpRect.right - EDGE_SCROLL_PX) {
        vp.scrollLeft += SCROLL_STEP;
      }
      if (e.clientY < vpRect.top + EDGE_SCROLL_PX) {
        vp.scrollTop = Math.max(0, vp.scrollTop - SCROLL_STEP);
      } else if (e.clientY > vpRect.bottom - EDGE_SCROLL_PX) {
        vp.scrollTop += SCROLL_STEP;
      }
    };

    const onUp = (e: PointerEvent) => {
      if (e.pointerId !== sess.pointerId) return;
      const dx = e.clientX - sess.startX;
      const dy = e.clientY - sess.startY;
      const dragged = Math.hypot(dx, dy) >= DRAG_THRESHOLD_PX;
      if (!dragged && !sess.additive) {
        setSelectedClipIds([]);
      }
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      cancelMarquee();
    };

    document.addEventListener("pointermove", onMove, { capture: true });
    document.addEventListener("pointerup", onUp, { capture: true });
    document.addEventListener("pointercancel", onUp, { capture: true });
    return () => {
      document.removeEventListener("pointermove", onMove, { capture: true });
      document.removeEventListener("pointerup", onUp, { capture: true });
      document.removeEventListener("pointercancel", onUp, { capture: true });
    };
  }, [
    sessionEpoch,
    timeline,
    pxPerSecond,
    marqueeMode,
    viewportRef,
    setSelectedClipIds,
    cancelMarquee,
  ]);

  const onLanePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      const t = e.target as HTMLElement;
      if (t.closest(".tl-clip")) return;
      if (!viewportRef.current || !timeline) return;
      e.stopPropagation();
      const additive = e.shiftKey;
      const base = additive ? [...useTimelineStore.getState().selectedClipIds] : [];
      sessionRef.current = {
        pointerId: e.pointerId,
        additive,
        startX: e.clientX,
        startY: e.clientY,
        baseSelection: base,
      };
      const canvas = viewportRef.current.querySelector<HTMLElement>(".timeline-canvas");
      try {
        canvas?.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      setSessionEpoch((n) => n + 1);
    },
    [timeline, viewportRef],
  );

  return { marquee, onLanePointerDown };
}
