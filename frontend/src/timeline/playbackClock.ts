import type { TimelineV2 } from "./types";
import { clipTimelineDuration, timelineEnd } from "./duration";

/** Advance playhead while playing; returns clamped time and whether timeline ended. */
export function advancePlayhead(
  playhead: number,
  dtSeconds: number,
  maxTime: number,
): { time: number; atEnd: boolean } {
  const next = playhead + Math.max(0, dtSeconds);
  if (next >= maxTime - 1e-6) {
    return { time: maxTime, atEnd: true };
  }
  return { time: next, atEnd: false };
}

export function videoTrackEnd(timeline: TimelineV2): number {
  let end = 0;
  for (const tr of timeline.tracks ?? []) {
    if (tr.type !== "video") continue;
    for (const c of tr.clips ?? []) {
      end = Math.max(
        end,
        c.timeline_start + clipTimelineDuration(c, "video"),
      );
    }
  }
  return end;
}

export function audioTrackEnd(timeline: TimelineV2): number {
  let end = 0;
  for (const tr of timeline.tracks ?? []) {
    if (tr.type !== "audio") continue;
    for (const c of tr.clips ?? []) {
      end = Math.max(
        end,
        c.timeline_start + clipTimelineDuration(c, "audio"),
      );
    }
  }
  return end;
}

/** Planner / load quality hint when audio runs past picture. */
export function timelinePlaybackQualityWarning(
  timeline: TimelineV2,
): string | null {
  const vEnd = videoTrackEnd(timeline);
  const aEnd = audioTrackEnd(timeline);
  const total = timelineEnd(timeline);
  if (vEnd < 0.05 && total > 0.05) {
    return "This plan has no video clips — preview is audio-only (black picture).";
  }
  if (aEnd > vEnd + 0.05) {
    return `Audio continues about ${(aEnd - vEnd).toFixed(1)}s past the last video clip — you may hear sound over a black frame.`;
  }
  return null;
}
