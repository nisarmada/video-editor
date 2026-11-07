import type { TimelineV2 } from "../timeline/types";
import type { TargetMode } from "./types";
import { getActionDefinition } from "./actions";
import { getCursorContext } from "../store/cursorContextStore";
import type { ShortcutTargetingPolicy } from "../store/editorSettingsStore";
import type { PerActionTargetOverrideMap } from "../store/editorSettingsStore";
import {
  rawSecondsFromClientXInTimeline,
  clipAtTimeOnTrack,
  findTrackUnderPoint,
} from "../timeline/timelinePointer";
import { timelineViewportElRef } from "../store/editorSettingsStore";
import { snapShortcutTime } from "./snapTime";
import {
  clipLinkingEnabled,
  expandSelectionWithAvLinks,
  findClipById,
} from "../timeline/selection";
import { useEditorSettingsStore } from "../store/editorSettingsStore";
import { clipTimelineDuration } from "../timeline/duration";

export type ResolvedShortcutTarget = {
  useCursorTime: boolean;
  timeSeconds: number;
  trackId: string | null;
  trackType: import("../timeline/types").TrackType | null;
  /** Primary clip for single-clip ops */
  primaryClipId: string | null;
  /** Multi-select clip ids when selection path applies */
  clipIds: string[];
  /** After expandSelectionWithAvLinks when Sel link is on */
  expandedClipIds: string[];
  fallbackNoClip: boolean;
  message: string | null;
};

function effectiveTargetMode(
  actionId: string,
  perAction: PerActionTargetOverrideMap,
): TargetMode {
  const o = perAction[actionId];
  if (o) return o;
  return getActionDefinition(actionId)?.targetMode ?? "global";
}

function policyUsesTimelineCursor(policy: ShortcutTargetingPolicy, region: string): boolean {
  if (policy === "cursor") {
    return region === "timeline" || region === "ruler";
  }
  if (policy === "cursor_else_playhead") {
    return region === "timeline" || region === "ruler";
  }
  return false;
}

export function resolveTarget(
  actionId: string,
  opts: {
    policy: ShortcutTargetingPolicy;
    perActionTargetMode: PerActionTargetOverrideMap;
    timelineSnapEnabled: boolean;
    pxPerSecond: number;
    playheadSeconds: number;
    timeline: TimelineV2 | null;
    selectedClipIds: string[];
    selectedClipId: string | null;
  },
): ResolvedShortcutTarget {
  let mode = effectiveTargetMode(actionId, opts.perActionTargetMode);
  if (opts.policy === "playhead" && mode === "cursor") {
    mode = "playhead";
  }
  const cur = getCursorContext();
  const tl = opts.timeline;

  const empty: ResolvedShortcutTarget = {
    useCursorTime: false,
    timeSeconds: opts.playheadSeconds,
    trackId: null,
    trackType: null,
    primaryClipId: null,
    clipIds: [],
    expandedClipIds: [],
    fallbackNoClip: true,
    message: null,
  };

  if (mode === "global") {
    return {
      ...empty,
      fallbackNoClip: false,
      timeSeconds: opts.playheadSeconds,
      clipIds: opts.selectedClipIds.length
        ? [...opts.selectedClipIds]
        : opts.selectedClipId
          ? [opts.selectedClipId]
          : [],
      primaryClipId: opts.selectedClipId,
    };
  }

  if (mode === "playhead") {
    return {
      ...empty,
      fallbackNoClip: false,
      timeSeconds: opts.playheadSeconds,
      clipIds: opts.selectedClipIds.length
        ? [...opts.selectedClipIds]
        : opts.selectedClipId
          ? [opts.selectedClipId]
          : [],
      primaryClipId: opts.selectedClipId,
    };
  }

  /* selection-only: ignore cursor region for clip pick */
  if (mode === "selection") {
    const ids = opts.selectedClipIds.length
      ? [...opts.selectedClipIds]
      : opts.selectedClipId
        ? [opts.selectedClipId]
        : [];
    return {
      ...empty,
      fallbackNoClip: ids.length === 0,
      timeSeconds: opts.playheadSeconds,
      clipIds: ids,
      primaryClipId: opts.selectedClipId,
      message: ids.length === 0 ? "No clip selected." : null,
    };
  }

  /* cursor */
  const useTl =
    opts.policy !== "playhead" &&
    policyUsesTimelineCursor(opts.policy, cur.region) &&
    cur.hasFinePointer &&
    (cur.region === "timeline" || cur.region === "ruler");

  if (!useTl || !tl) {
    return {
      ...empty,
      fallbackNoClip: false,
      timeSeconds: opts.playheadSeconds,
      clipIds: opts.selectedClipIds.length
        ? [...opts.selectedClipIds]
        : opts.selectedClipId
          ? [opts.selectedClipId]
          : [],
      primaryClipId: opts.selectedClipId,
    };
  }

  const vp = timelineViewportElRef.current;
  const raw = rawSecondsFromClientXInTimeline(
    cur.clientX,
    vp,
    opts.pxPerSecond,
  );
  /* Hit-test which clip is under the pointer (unsnapped). Snap only for time-based edits. */
  const tSnap = snapShortcutTime(
    raw,
    tl,
    opts.pxPerSecond,
    opts.playheadSeconds,
    opts.timelineSnapEnabled,
  );

  const sub = cur.region === "ruler" ? "ruler" : "lane";
  let trackId = cur.trackIdAtCursor;
  let trackType = cur.trackTypeAtCursor;
  let clipId = cur.clipIdAtCursor;

  if (sub === "ruler" || !trackId) {
    let yProbe = cur.clientY;
    if (sub === "ruler" && vp) {
      const firstLane = vp.querySelector<HTMLElement>("[data-track-lane-id]");
      if (firstLane) {
        const r = firstLane.getBoundingClientRect();
        yProbe = r.top + Math.min(8, r.height / 2);
      }
    }
    const hit = vp ? findTrackUnderPoint(vp, yProbe) : null;
    if (hit) {
      trackId = hit.trackId;
      trackType = hit.trackType;
      const hitClip = clipAtTimeOnTrack(tl, trackId, raw);
      clipId = hitClip?.clipId ?? null;
    }
  } else if (trackId && clipId === null) {
    const hitClip = clipAtTimeOnTrack(tl, trackId, raw);
    clipId = hitClip?.clipId ?? null;
  }

  const selList =
    opts.selectedClipIds.length > 0
      ? [...opts.selectedClipIds]
      : opts.selectedClipId
        ? [opts.selectedClipId]
        : [];
  const selSet = new Set(selList);

  function clipContainsTime(id: string, t: number): boolean {
    const hit = findClipById(tl!, id);
    if (!hit) return false;
    const d = clipTimelineDuration(hit.clip, hit.trackType);
    const t0 = hit.clip.timeline_start;
    const t1 = t0 + d;
    /* Half-open [start, end) — include start boundary */
    return t >= t0 - 1e-9 && t < t1 - 1e-9;
  }

  let primaryClipId: string | null = clipId;
  let baseIds: string[] = [];

  if (!clipId) {
    baseIds = [];
  } else if (selSet.has(clipId) && selSet.size > 1) {
    baseIds = selList.filter((id) => clipContainsTime(id, raw));
  } else {
    baseIds = [clipId];
  }

  const selectLinked =
    useEditorSettingsStore.getState().selectLinkedClipsTogether;
  let clipIds =
    baseIds.length > 0
      ? expandSelectionWithAvLinks(tl!, baseIds, selectLinked)
      : baseIds;

  clipIds = clipIds.filter((id) => clipContainsTime(id, raw));
  primaryClipId = clipIds[0] ?? clipId;

  const fallbackNoClip = clipIds.length === 0;
  const message: string | null = fallbackNoClip
    ? "No clip under the cursor."
    : null;

  return {
    useCursorTime: true,
    timeSeconds: tSnap,
    trackId,
    trackType,
    primaryClipId,
    clipIds,
    expandedClipIds: [...clipIds],
    fallbackNoClip,
    message,
  };
}
