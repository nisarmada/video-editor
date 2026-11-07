import { describe, expect, it } from "vitest";
import {
  activeVideoClipAt,
  clipTimelineDuration,
  getSortedVideoClips,
} from "./duration";
import type { TimelineClip, TimelineV2 } from "./types";

describe("getSortedVideoClips", () => {
  it("merges clips from all video tracks sorted by timeline_start", () => {
    const timeline: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "v1",
          type: "video",
          clips: [
            {
              id: "a",
              source: "footage/a.mp4",
              source_in: 0,
              source_out: 5,
              timeline_start: 0,
              created_by: "user",
            },
          ],
        },
        {
          id: "v2",
          type: "video",
          clips: [
            {
              id: "b",
              source: "footage/b.mp4",
              source_in: 0,
              source_out: 5,
              timeline_start: 2,
              created_by: "user",
            },
          ],
        },
        { id: "a1", type: "audio", clips: [] },
      ],
    };
    const clips = getSortedVideoClips(timeline);
    expect(clips.map((c) => c.id)).toEqual(["a", "b"]);
  });
});

describe("activeVideoClipAt", () => {
  it("returns the top-layer clip when two video tracks overlap in time", () => {
    const cBottom = {
      id: "bottom",
      source: "footage/a.mp4",
      source_in: 0,
      source_out: 10,
      timeline_start: 0,
      created_by: "user",
    };
    const cTop = {
      id: "top",
      source: "footage/b.mp4",
      source_in: 0,
      source_out: 10,
      timeline_start: 1,
      created_by: "user",
    };
    const timeline: TimelineV2 = {
      schema_version: 2,
      tracks: [
        { id: "v1", type: "video", clips: [cBottom] },
        { id: "v2", type: "video", clips: [cTop] },
        { id: "a1", type: "audio", clips: [] },
      ],
    };
    const clips = getSortedVideoClips(timeline);
    expect(clipTimelineDuration(cBottom, "video")).toBe(10);
    expect(activeVideoClipAt(clips, 0.5)?.id).toBe("bottom");
    expect(activeVideoClipAt(clips, 3)?.id).toBe("top");
  });

  it("supports two sequential clips on one track (second clip is visible at its start)", () => {
    const c1 = {
      id: "first",
      source: "footage/same.mp4",
      source_in: 0,
      source_out: 5,
      timeline_start: 0,
      created_by: "user",
    };
    const c2 = {
      id: "second",
      source: "footage/same.mp4",
      source_in: 0,
      source_out: 5,
      timeline_start: 5,
      created_by: "user",
    };
    const timeline: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "v1",
          type: "video",
          clips: [c1, c2],
        },
        { id: "a1", type: "audio", clips: [] },
      ],
    };
    const clips = getSortedVideoClips(timeline);
    expect(activeVideoClipAt(clips, 4.9)?.id).toBe("first");
    expect(activeVideoClipAt(clips, 5)?.id).toBe("second");
  });

  it("does not fall through a float gap between split neighbors (still shows second clip)", () => {
    const leftEnd = 0.3 + 0.7; // float drift from 1.0
    const c1 = {
      id: "left",
      source: "footage/a.mp4",
      source_in: 0,
      source_out: leftEnd,
      timeline_start: 0,
      created_by: "user",
    };
    const c2 = {
      id: "right",
      source: "footage/a.mp4",
      source_in: leftEnd,
      source_out: 10,
      timeline_start: leftEnd,
      created_by: "user",
    };
    const timeline: TimelineV2 = {
      schema_version: 2,
      tracks: [{ id: "v1", type: "video", clips: [c1, c2] }, { id: "a1", type: "audio", clips: [] }],
    };
    const clips = getSortedVideoClips(timeline);
    // Timeline "join" is float-imprecise — without end slack this can be neither clip.
    const join = clipTimelineDuration(c1, "video") + c1.timeline_start;
    expect(activeVideoClipAt(clips, join)?.id).toBe("right");
  });
});

describe("clipTimelineDuration (caption)", () => {
  it("uses timeline_end or text heuristic when source span is missing", () => {
    const withEnd: TimelineClip = {
      id: "c1",
      text: "Hi",
      timeline_start: 1,
      timeline_end: 4,
      created_by: "user",
    };
    expect(clipTimelineDuration(withEnd, "caption")).toBe(3);

    const textOnly = {
      id: "c2",
      text: "A longer caption line",
      timeline_start: 0,
      created_by: "user" as const,
    };
    expect(clipTimelineDuration(textOnly, "caption")).toBeGreaterThan(0.5);
  });
});
