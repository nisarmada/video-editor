import type { TrackType } from "./types";
import { clipTimelineDuration } from "./duration";
import type { TimelineV2 } from "./types";
import { TIMELINE_LABEL_WIDTH, TIMELINE_RULER_HEIGHT } from "./timelineLayout";

export {
  TIMELINE_LABEL_WIDTH,
  TIMELINE_RULER_HEIGHT,
  TIMELINE_TRACK_HEIGHT,
} from "./timelineLayout";

export function laneContentXFromClient(
  clientX: number,
  laneEl: HTMLElement,
  viewportEl: HTMLElement | null,
): number {
  const laneRect = laneEl.getBoundingClientRect();
  const scrollLeft = viewportEl?.scrollLeft ?? 0;
  return clientX - laneRect.left + scrollLeft;
}

export function findTrackUnderPoint(
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

/** Seconds along the lane from a client X (no snapping). */
export function rawSecondsFromClientXInTimeline(
  clientX: number,
  viewportEl: HTMLElement | null,
  pxPerSecond: number,
): number {
  if (!viewportEl || pxPerSecond <= 0) return 0;
  const canvas = viewportEl.querySelector<HTMLElement>(".timeline-canvas");
  if (!canvas) return 0;
  const rect = canvas.getBoundingClientRect();
  const xContent = clientX - rect.left - TIMELINE_LABEL_WIDTH + viewportEl.scrollLeft;
  const sec = xContent / pxPerSecond;
  return Number.isFinite(sec) ? Math.max(0, sec) : 0;
}

export function clipAtTimeOnTrack(
  timeline: TimelineV2,
  trackId: string,
  t: number,
): { clipId: string; offsetInClip: number } | null {
  const tr = timeline.tracks?.find((x) => x.id === trackId);
  if (!tr) return null;
  for (const c of tr.clips ?? []) {
    const dur = clipTimelineDuration(c, tr.type);
    const start = c.timeline_start;
    const end = start + dur;
    if (t >= start - 1e-9 && t < end - 1e-9) {
      return { clipId: c.id, offsetInClip: t - start };
    }
  }
  return null;
}

/** Whether client point is in timeline canvas (ruler + tracks), in content coordinates sense. */
export function isClientOverTimelineCanvas(
  viewportEl: HTMLElement | null,
  clientX: number,
  clientY: number,
): boolean {
  if (!viewportEl) return false;
  const canvas = viewportEl.querySelector<HTMLElement>(".timeline-canvas");
  if (!canvas) return false;
  const r = canvas.getBoundingClientRect();
  return (
    clientX >= r.left &&
    clientX <= r.right &&
    clientY >= r.top &&
    clientY <= r.bottom
  );
}

export function timelineSubRegion(
  viewportEl: HTMLElement | null,
  clientX: number,
  clientY: number,
): "ruler" | "lane" | null {
  if (!viewportEl || !isClientOverTimelineCanvas(viewportEl, clientX, clientY)) {
    return null;
  }
  const canvas = viewportEl.querySelector<HTMLElement>(".timeline-canvas");
  if (!canvas) return null;
  const cr = canvas.getBoundingClientRect();
  const relY = clientY - cr.top;
  if (relY < TIMELINE_RULER_HEIGHT) return "ruler";
  return "lane";
}
