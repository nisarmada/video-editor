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

type GroupMember = { id: string; trackType: string; clip: TimelineClip };

/** Video/audio clips with the same group_id (never caption). */
function avMembersWithGroupId(timeline: TimelineV2, groupId: string): GroupMember[] {
  const out: GroupMember[] = [];
  for (const tr of timeline.tracks ?? []) {
    if (tr.type !== "video" && tr.type !== "audio") continue;
    for (const c of tr.clips ?? []) {
      if (c.group_id === groupId && c.id) {
        out.push({ id: c.id, trackType: tr.type, clip: c });
      }
    }
  }
  return out;
}

/**
 * Explicit A/V pair only: `group_kind === "av_link"`, or legacy separated pair
 * (exactly one video + one audio, same group_id, video audio_source detached).
 * Never caption; never when more than two A/V clips share a group_id.
 */
export function avLinkPartnerId(timeline: TimelineV2, clipId: string): string | null {
  const hit = findClipById(timeline, clipId);
  if (!hit || hit.trackType === "caption") return null;
  const gid = hit.clip.group_id?.trim();
  if (!gid) return null;

  const members = avMembersWithGroupId(timeline, gid);
  if (members.length !== 2) return null;

  const hasVideo = members.some((m) => m.trackType === "video");
  const hasAudio = members.some((m) => m.trackType === "audio");
  if (!hasVideo || !hasAudio) return null;

  const explicit =
    hit.clip.group_kind === "av_link" ||
    members.every((m) => m.clip.group_kind === "av_link");
  const legacy =
    !explicit &&
    hit.trackType === "video" &&
    hit.clip.audio_source === "detached" &&
    members.some((m) => m.trackType === "audio");
  if (!explicit && !legacy) return null;

  const other = members.find((m) => m.id !== clipId);
  return other?.id ?? null;
}

/** @deprecated Use avLinkPartnerId — first partner for link icon hover. */
export function linkedPartnerId(timeline: TimelineV2, clipId: string): string | null {
  return avLinkPartnerId(timeline, clipId);
}

/** Ids to select when user picks clipId (0–1 AV partner). */
export function selectionIdsForClick(
  timeline: TimelineV2,
  clipId: string,
  selectLinkedTogether: boolean,
): string[] {
  if (!selectLinkedTogether) return [clipId];
  const partner = avLinkPartnerId(timeline, clipId);
  return partner ? [clipId, partner] : [clipId];
}

/** Expand each id with its AV partner when enabled; never planner-wide group_id. */
export function expandSelectionWithAvLinks(
  timeline: TimelineV2,
  ids: string[],
  selectLinkedTogether: boolean,
): string[] {
  if (!selectLinkedTogether) return [...new Set(ids)];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const id of ids) {
    for (const x of selectionIdsForClick(timeline, id, true)) {
      if (seen.has(x)) continue;
      seen.add(x);
      out.push(x);
    }
  }
  return out;
}

/** @deprecated Use expandSelectionWithAvLinks / selectionIdsForClick instead. */
export function expandLinkedSelection(
  timeline: TimelineV2,
  ids: string[],
  selectLinkedTogether = clipLinkingEnabled(timeline),
): string[] {
  return expandSelectionWithAvLinks(timeline, ids, selectLinkedTogether);
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

export type ClipboardMultiEntry = ClipboardClipPayload & {
  timelineStart: number;
  trackIndex: number;
};

export type ClipboardPayload =
  | { kind: "single"; item: ClipboardClipPayload }
  | { kind: "multi"; items: ClipboardMultiEntry[]; anchorTime: number };

export function pruneClipIds(timeline: TimelineV2 | null, ids: string[]): string[] {
  if (!timeline || ids.length === 0) return [];
  const live = new Set<string>();
  for (const tr of timeline.tracks ?? []) {
    for (const c of tr.clips ?? []) {
      live.add(c.id);
    }
  }
  return ids.filter((id) => live.has(id));
}

export function allClipIds(timeline: TimelineV2): string[] {
  const ids: string[] = [];
  for (const tr of timeline.tracks ?? []) {
    for (const c of tr.clips ?? []) {
      if (c.id) ids.push(c.id);
    }
  }
  return ids;
}

export function copyClipPayload(payload: ClipboardClipPayload): void {
  writeClipboard({ kind: "single", item: payload });
}

export function copyClipsPayload(items: ClipboardMultiEntry[]): void {
  if (items.length === 0) return;
  if (items.length === 1) {
    const one = items[0]!;
    writeClipboard({
      kind: "single",
      item: {
        clip: one.clip,
        sourceTrackId: one.sourceTrackId,
        sourceTrackType: one.sourceTrackType,
      },
    });
    return;
  }
  const anchorTime = Math.min(...items.map((x) => x.timelineStart));
  writeClipboard({ kind: "multi", items, anchorTime });
}

function writeClipboard(data: ClipboardPayload): void {
  try {
    sessionStorage.setItem(CLIPBOARD_KEY, JSON.stringify(data));
  } catch {
    /* ignore */
  }
}

export function readClipFromClipboard(): ClipboardClipPayload | null {
  const p = readClipboardPayload();
  if (!p) return null;
  if (p.kind === "single") return p.item;
  const first = p.items[0];
  if (!first) return null;
  return {
    clip: first.clip,
    sourceTrackId: first.sourceTrackId,
    sourceTrackType: first.sourceTrackType,
  };
}

export function readClipboardPayload(): ClipboardPayload | null {
  try {
    const raw = sessionStorage.getItem(CLIPBOARD_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as unknown;
    if (!data || typeof data !== "object") return null;
    if ("kind" in (data as object)) {
      return data as ClipboardPayload;
    }
    const legacy = data as ClipboardClipPayload | TimelineClip;
    if (legacy && typeof legacy === "object" && "clip" in legacy) {
      return { kind: "single", item: legacy as ClipboardClipPayload };
    }
    return null;
  } catch {
    return null;
  }
}

export function playheadInsideClip(
  clip: TimelineClip,
  trackType: string,
  playhead: number,
): boolean {
  const dur = clipTimelineDuration(clip, trackType);
  const end = clip.timeline_start + dur;
  return playhead >= clip.timeline_start - 1e-9 && playhead < end - 1e-9;
}
