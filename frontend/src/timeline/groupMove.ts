import { clipTimelineDuration } from "./duration";
import { findClipById } from "./selection";
import type { TimelineV2 } from "./types";

const EPS = 1e-6;

export type GroupMovePlan = {
  clipId: string;
  trackId: string;
  newStart: number;
};

export type GroupMoveValidation =
  | { ok: true; moves: GroupMovePlan[] }
  | { ok: false; message: string };

/**
 * Horizontal group move: every clip shifts by the same delta, stays on its track.
 */
export function validateGroupMove(
  timeline: TimelineV2,
  clipIds: string[],
  deltaSec: number,
): GroupMoveValidation {
  if (clipIds.length === 0) {
    return { ok: false, message: "No clips to move." };
  }
  const moving = new Set(clipIds);
  const plans: GroupMovePlan[] = [];

  for (const id of clipIds) {
    const hit = findClipById(timeline, id);
    if (!hit) {
      return { ok: false, message: "Selection includes a missing clip." };
    }
    const tr = timeline.tracks?.find((x) => x.id === hit.trackId);
    if (tr?.locked) {
      return { ok: false, message: "A selected clip is on a locked track." };
    }
    const next = hit.clip.timeline_start + deltaSec;
    if (next < -EPS) {
      return { ok: false, message: "Move would place a clip before time 0." };
    }
    plans.push({ clipId: id, trackId: hit.trackId, newStart: Math.max(0, next) });
  }

  for (const tr of timeline.tracks ?? []) {
    const intervals: { start: number; end: number; id: string }[] = [];
    for (const c of tr.clips ?? []) {
      const dur = clipTimelineDuration(c, tr.type);
      const start = moving.has(c.id)
        ? plans.find((p) => p.clipId === c.id)!.newStart
        : c.timeline_start;
      intervals.push({ start, end: start + dur, id: c.id });
    }
    intervals.sort((a, b) => a.start - b.start);
    for (let j = 0; j < intervals.length - 1; j++) {
      const a = intervals[j]!;
      const b = intervals[j + 1]!;
      if (b.start < a.end - EPS) {
        return {
          ok: false,
          message: `Clips would overlap on ${tr.label ?? tr.type} track.`,
        };
      }
    }
  }

  return { ok: true, moves: plans };
}
