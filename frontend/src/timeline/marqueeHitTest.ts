import { clipTimelineDuration } from "./duration";
import {
  TIMELINE_LABEL_WIDTH,
  TIMELINE_RULER_HEIGHT,
  TIMELINE_TRACK_HEIGHT,
} from "./timelineLayout";

/** Match .tl-clip { top: 8px; height: 32px } in App.css */
const CLIP_INSET_TOP = 8;
const CLIP_BAND_HEIGHT = 32;
import type { TimelineV2 } from "./types";
import { orderedTracks } from "./selection";

export type MarqueeOverlapMode = "touch" | "inside";

export type ContentRect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

export type ClipLayoutRect = ContentRect & {
  clipId: string;
  trackId: string;
  trackIndex: number;
};

function rectsOverlap(a: ContentRect, b: ContentRect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function aContainsB(outer: ContentRect, inner: ContentRect): boolean {
  return (
    inner.left >= outer.left &&
    inner.right <= outer.right &&
    inner.top >= outer.top &&
    inner.bottom <= outer.bottom
  );
}

/** Clip boxes in timeline-canvas content coordinates (scroll-independent). */
export function buildClipLayoutRects(
  timeline: TimelineV2,
  pxPerSecond: number,
): ClipLayoutRect[] {
  const tracks = orderedTracks(timeline);
  const out: ClipLayoutRect[] = [];
  tracks.forEach((tr, trackIndex) => {
    const rowTop = TIMELINE_RULER_HEIGHT + trackIndex * TIMELINE_TRACK_HEIGHT;
    const clipTop = rowTop + CLIP_INSET_TOP;
    const clipBottom = clipTop + CLIP_BAND_HEIGHT;
    for (const c of tr.clips ?? []) {
      const dur = clipTimelineDuration(c, tr.type);
      const left = TIMELINE_LABEL_WIDTH + c.timeline_start * pxPerSecond;
      const right = left + Math.max(dur * pxPerSecond, 4);
      out.push({
        clipId: c.id,
        trackId: tr.id,
        trackIndex,
        left,
        top: clipTop,
        right,
        bottom: clipBottom,
      });
    }
  });
  return out;
}

export function clipsInMarqueeRect(
  layout: ClipLayoutRect[],
  marquee: ContentRect,
  mode: MarqueeOverlapMode,
): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const r of layout) {
    const hit =
      mode === "inside" ? aContainsB(marquee, r) : rectsOverlap(marquee, r);
    if (hit && !seen.has(r.clipId)) {
      seen.add(r.clipId);
      ids.push(r.clipId);
    }
  }
  return ids;
}

export function normalizeMarquee(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): ContentRect {
  return {
    left: Math.min(x0, x1),
    top: Math.min(y0, y1),
    right: Math.max(x0, x1),
    bottom: Math.max(y0, y1),
  };
}

/** Client coords → content coords inside `.timeline-canvas`. */
export function clientToCanvasContent(
  clientX: number,
  clientY: number,
  canvasRect: DOMRect,
  scrollLeft: number,
  scrollTop: number,
): { x: number; y: number } {
  return {
    x: clientX - canvasRect.left + scrollLeft,
    y: clientY - canvasRect.top + scrollTop,
  };
}
