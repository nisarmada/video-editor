import type { TimelineV2 } from "../timeline/types";
import { clipTimelineDuration } from "../timeline/duration";
import { TIMELINE_SNAP_SEC } from "../timeline/dragConstants";

/** ~6px in time units — used when “timeline snap” is on (edge / playhead magnet). */
export function snapPixelThresholdSec(pxPerSecond: number): number {
  if (pxPerSecond <= 0) return 0.05;
  return 6 / pxPerSecond;
}

function collectClipEdgeTimes(timeline: TimelineV2): number[] {
  const out: number[] = [];
  for (const tr of timeline.tracks ?? []) {
    for (const c of tr.clips ?? []) {
      const t0 = c.timeline_start;
      const t1 = t0 + clipTimelineDuration(c, tr.type);
      out.push(t0, t1);
    }
  }
  return out;
}

/**
 * When timeline snap is on: snap to nearest clip edge or playhead within ~6px, else frame grid.
 * When off: frame grid only.
 */
export function snapShortcutTime(
  rawSec: number,
  timeline: TimelineV2 | null,
  pxPerSecond: number,
  playhead: number,
  timelineSnapEnabled: boolean,
): number {
  const fps =
    timeline?.settings?.fps && timeline.settings.fps > 0 ? timeline.settings.fps : 30;
  const frame = 1 / fps;

  if (!timeline) {
    return Math.max(0, Math.round(rawSec / frame) * frame);
  }

  const thresh = snapPixelThresholdSec(pxPerSecond);
  let best = rawSec;
  let bestDist = Infinity;

  if (timelineSnapEnabled) {
    const candidates = new Set<number>([playhead, 0, ...collectClipEdgeTimes(timeline)]);
    for (const t of candidates) {
      const d = Math.abs(t - rawSec);
      if (d <= thresh + 1e-9 && d < bestDist) {
        bestDist = d;
        best = t;
      }
    }
    if (bestDist < Infinity) {
      return Math.max(0, best);
    }
  }

  /* Frame grid (TIMELINE_SNAP_SEC step is legacy drag snap; shortcuts use frame) */
  const snapped = Math.round(rawSec / frame) * frame;
  const legacy = Math.round(rawSec / TIMELINE_SNAP_SEC) * TIMELINE_SNAP_SEC;
  /* Prefer frame grid for shortcuts */
  void legacy;
  return Math.max(0, snapped);
}

export function isTooCloseToClipEdgeForSplit(
  snappedTime: number,
  clipStart: number,
  clipEnd: number,
  fps: number,
): boolean {
  const frame = 1 / fps;
  const margin = frame - 1e-6;
  return (
    Math.abs(snappedTime - clipStart) < margin ||
    Math.abs(snappedTime - clipEnd) < margin
  );
}
