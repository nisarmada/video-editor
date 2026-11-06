import type { TimelineClip, TimelineV2 } from "./types";
import { clipTimelineDuration } from "./duration";

/** Display order: all video tracks, then all audio, then captions (others last). */
export function orderedTracks(timeline: TimelineV2) {
  const tracks = [...(timeline.tracks ?? [])];
  const rank = (t: string) =>
    t === "video" ? 0 : t === "audio" ? 1 : t === "caption" ? 2 : 3;
  return tracks.sort((a, b) => rank(a.type) - rank(b.type) || a.id.localeCompare(b.id));
}

export function findClipById(
  timeline: TimelineV2,
  clipId: string,
): { trackId: string; trackType: string; clip: TimelineClip } | null {
  for (const tr of timeline.tracks ?? []) {
    for (const c of tr.clips ?? []) {
      if (c.id === clipId) {
        return { trackId: tr.id, trackType: tr.type, clip: c };
      }
    }
  }
  return null;
}

/** Linked partner on the other video/audio track (same group_id). */
export function linkedPartnerId(timeline: TimelineV2, clipId: string): string | null {
  const hit = findClipById(timeline, clipId);
  if (!hit) return null;
  const gid = hit.clip.group_id;
  if (!gid?.trim()) return null;
  const wantType = hit.trackType === "video" ? "audio" : "video";
  if (hit.trackType === "caption") return null;
  for (const tr of timeline.tracks ?? []) {
    if (tr.type !== wantType) continue;
    for (const c of tr.clips ?? []) {
      if (c.id !== clipId && c.group_id === gid) return c.id;
    }
  }
  return null;
}

export function expandLinkedSelection(timeline: TimelineV2, ids: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const id of ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(id);
    const partner = linkedPartnerId(timeline, id);
    if (partner && !seen.has(partner)) {
      seen.add(partner);
      out.push(partner);
    }
  }
  return out;
}

export function clipLinkingEnabled(timeline: TimelineV2 | null): boolean {
  const v = timeline?.settings?.clip_linking_enabled;
  return v !== false;
}

const CLIPBOARD_KEY = "video-editor-timeline-clip-json";

export type ClipboardClipPayload = {
  clip: TimelineClip;
  sourceTrackId: string;
  sourceTrackType: string;
};

export function copyClipPayload(payload: ClipboardClipPayload): void {
  try {
    sessionStorage.setItem(CLIPBOARD_KEY, JSON.stringify(payload));
  } catch {
    /* ignore */
  }
}

export function readClipFromClipboard(): ClipboardClipPayload | null {
  try {
    const raw = sessionStorage.getItem(CLIPBOARD_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as ClipboardClipPayload | TimelineClip;
    if (data && typeof data === "object" && "clip" in data) {
      return data as ClipboardClipPayload;
    }
    return null;
  } catch {
    return null;
  }
}

/** True if playhead lies strictly inside clip span on timeline. */
export function playheadInsideClip(
  clip: TimelineClip,
  trackType: string,
  playhead: number,
): boolean {
  const dur = clipTimelineDuration(clip, trackType);
  const end = clip.timeline_start + dur;
  return playhead >= clip.timeline_start - 1e-9 && playhead < end - 1e-9;
}
