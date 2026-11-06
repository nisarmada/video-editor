import { describe, expect, it, beforeEach } from "vitest";
import { resolveTarget } from "./resolveTarget";
import {
  resetCursorContext,
  updateCursorContextPartial,
} from "../store/cursorContextStore";
import { timelineViewportElRef } from "../store/editorSettingsStore";
import type { TimelineV2 } from "../timeline/types";

function sampleTimeline(): TimelineV2 {
  return {
    schema_version: 2,
    settings: { fps: 30, clip_linking_enabled: false },
    tracks: [
      {
        id: "v1",
        type: "video",
        clips: [
          {
            id: "c1",
            timeline_start: 0,
            source_in: 0,
            source_out: 10,
          },
          {
            id: "c2",
            timeline_start: 10,
            source_in: 0,
            source_out: 5,
          },
        ],
      },
      { id: "a1", type: "audio", clips: [] },
    ],
  };
}

beforeEach(() => {
  resetCursorContext();
  timelineViewportElRef.current = null;
});

describe("resolveTarget", () => {
  it("uses playhead + selection when not over timeline", () => {
    const tl = sampleTimeline();
    updateCursorContextPartial({
      region: "none",
      hasFinePointer: true,
      clientX: 0,
      clientY: 0,
    });
    const r = resolveTarget("split", {
      policy: "cursor",
      perActionTargetMode: {},
      timelineSnapEnabled: false,
      pxPerSecond: 48,
      playheadSeconds: 2,
      timeline: tl,
      selectedClipIds: ["c1"],
      selectedClipId: "c1",
    });
    expect(r.useCursorTime).toBe(false);
    expect(r.timeSeconds).toBe(2);
    expect(r.clipIds).toEqual(["c1"]);
  });

  it("uses cursor clip when over timeline (viewport null → raw time 0)", () => {
    const tl = sampleTimeline();
    updateCursorContextPartial({
      region: "timeline",
      hasFinePointer: true,
      clientX: 0,
      clientY: 0,
      trackIdAtCursor: "v1",
      trackTypeAtCursor: "video",
      clipIdAtCursor: "c1",
    });
    const r = resolveTarget("split", {
      policy: "cursor",
      perActionTargetMode: {},
      timelineSnapEnabled: false,
      pxPerSecond: 48,
      playheadSeconds: 99,
      timeline: tl,
      selectedClipIds: [],
      selectedClipId: null,
    });
    expect(r.useCursorTime).toBe(true);
    expect(r.clipIds).toEqual(["c1"]);
    expect(r.timeSeconds).toBeGreaterThanOrEqual(0);
  });

  it("gap reports no clip", () => {
    const tl = sampleTimeline();
    /* Move first clip so t=0 is empty on the track */
    tl.tracks[0]!.clips![0]!.timeline_start = 5;
    tl.tracks[0]!.clips![1]!.timeline_start = 20;
    updateCursorContextPartial({
      region: "timeline",
      hasFinePointer: true,
      trackIdAtCursor: "v1",
      trackTypeAtCursor: "video",
      clipIdAtCursor: null,
    });

    const r = resolveTarget("delete", {
      policy: "cursor",
      perActionTargetMode: {},
      timelineSnapEnabled: false,
      pxPerSecond: 48,
      playheadSeconds: 5,
      timeline: tl,
      selectedClipIds: [],
      selectedClipId: null,
    });
    expect(r.fallbackNoClip).toBe(true);
  });

  it("policy playhead forces playhead time even over timeline", () => {
    const tl = sampleTimeline();
    updateCursorContextPartial({
      region: "timeline",
      hasFinePointer: true,
      trackIdAtCursor: "v1",
      trackTypeAtCursor: "video",
      clipIdAtCursor: "c1",
    });
    const r = resolveTarget("split", {
      policy: "playhead",
      perActionTargetMode: {},
      timelineSnapEnabled: false,
      pxPerSecond: 48,
      playheadSeconds: 3,
      timeline: tl,
      selectedClipIds: ["c1"],
      selectedClipId: "c1",
    });
    expect(r.useCursorTime).toBe(false);
    expect(r.timeSeconds).toBe(3);
  });

  it("multi-selection filters to clips containing raw cursor time", () => {
    const tl = sampleTimeline();
    updateCursorContextPartial({
      region: "timeline",
      hasFinePointer: true,
      clientX: 0,
      clientY: 0,
      trackIdAtCursor: "v1",
      trackTypeAtCursor: "video",
      clipIdAtCursor: "c1",
    });
    const r = resolveTarget("split", {
      policy: "cursor",
      perActionTargetMode: {},
      timelineSnapEnabled: false,
      pxPerSecond: 48,
      playheadSeconds: 0,
      timeline: tl,
      selectedClipIds: ["c1", "c2"],
      selectedClipId: "c1",
    });
    expect(r.clipIds).toEqual(["c1"]);
  });
});
