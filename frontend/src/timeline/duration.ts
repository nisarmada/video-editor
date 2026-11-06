import type { TimelineClip, TimelineV2 } from "./types";

export function clipTimelineDuration(
  clip: TimelineClip,
  trackType: string,
): number {
  const speed = clip.speed && clip.speed > 0 ? clip.speed : 1;
  const srcIn = clip.source_in ?? 0;
  const srcOut = clip.source_out ?? srcIn;
  const base = srcOut - srcIn;
  if (trackType === "caption") {
    return Math.max(0, base);
  }
  return Math.max(0, base / speed);
}

export function timelineEnd(timeline: TimelineV2): number {
  let end = 0;
  for (const track of timeline.tracks) {
    const ttype = track.type;
    for (const clip of track.clips ?? []) {
      const start = clip.timeline_start;
      const dur = clipTimelineDuration(clip, ttype);
      end = Math.max(end, start + dur);
    }
  }
  return end;
}

/** Short label on clip blocks. */
export function clipDisplayName(clip: TimelineClip, trackType: string): string {
  if (trackType === "caption" && clip.text) {
    const t = clip.text.trim();
    return t.length > 28 ? `${t.slice(0, 28)}…` : t;
  }
  if (clip.caption) {
    const t = clip.caption.trim();
    return t.length > 24 ? `${t.slice(0, 24)}…` : t;
  }
  if (clip.source) {
    const parts = clip.source.split("/");
    return parts[parts.length - 1] ?? clip.source;
  }
  return clip.id.slice(0, 8);
}

/**
 * All clips from every video track, sorted by timeline_start then track order.
 * Multiple video tracks are allowed (e.g. overlay); later tracks win on overlap (see activeVideoClipAt).
 */
export function getSortedVideoClips(timeline: TimelineV2 | null): TimelineClip[] {
  if (!timeline) return [];
  const tagged: { clip: TimelineClip; trackIndex: number }[] = [];
  timeline.tracks.forEach((tr, trackIndex) => {
    if (tr.type !== "video") return;
    for (const c of tr.clips ?? []) {
      tagged.push({ clip: c, trackIndex });
    }
  });
  tagged.sort((a, b) => {
    const d = a.clip.timeline_start - b.clip.timeline_start;
    if (d !== 0) return d;
    return a.trackIndex - b.trackIndex;
  });
  return tagged.map((x) => x.clip);
}

/**
 * Active video clip at timeline time t, or null in a gap.
 * Clips are half-open [start, end) so adjacent clips meet at boundaries.
 * If two video clips overlap (different tracks), the clip on the later track wins (top layer).
 */
export function activeVideoClipAt(
  clips: TimelineClip[],
  t: number,
): TimelineClip | null {
  let hit: TimelineClip | null = null;
  for (const clip of clips) {
    const dur = clipTimelineDuration(clip, "video");
    const start = clip.timeline_start;
    const end = start + dur;
    if (t >= start - 1e-9 && t < end - 1e-9) {
      hit = clip;
    }
  }
  return hit;
}

/** Map timeline time to source media time (seconds). */
export function timelineToSourceSeconds(clip: TimelineClip, playhead: number): number {
  const speed = clip.speed && clip.speed > 0 ? clip.speed : 1;
  const srcIn = clip.source_in ?? 0;
  return srcIn + (playhead - clip.timeline_start) * speed;
}

/** Proxy URL for API: footage/foo.mp4 -> /api/footage/foo.mp4/proxy */
export function proxyUrlFromSource(source: string): string {
  const name = source.split("/").pop() ?? source;
  return `/api/footage/${encodeURIComponent(name)}/proxy`;
}

export function trackClipClass(trackType: string): string {
  switch (trackType) {
    case "video":
      return "tl-clip tl-clip--video";
    case "audio":
      return "tl-clip tl-clip--audio";
    case "caption":
      return "tl-clip tl-clip--caption";
    default:
      return "tl-clip";
  }
}
