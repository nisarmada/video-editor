import { describe, expect, it } from "vitest";
import type { TimelineV2 } from "./types";
import {
  advancePlayhead,
  timelinePlaybackQualityWarning,
} from "./playbackClock";

describe("advancePlayhead", () => {
  it("advances in gaps and audio-only regions", () => {
    const { time, atEnd } = advancePlayhead(0, 0.5, 10);
    expect(time).toBe(0.5);
    expect(atEnd).toBe(false);
  });

  it("stops at timeline end", () => {
    const { time, atEnd } = advancePlayhead(9.9, 0.5, 10);
    expect(time).toBe(10);
    expect(atEnd).toBe(true);
  });
});

describe("timelinePlaybackQualityWarning", () => {
  it("warns when audio extends past video", () => {
    const tl: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "v",
          type: "video",
          clips: [
            {
              id: "1",
              source: "footage/a.mp4",
              source_in: 0,
              source_out: 2,
              timeline_start: 0,
            },
          ],
        },
        {
          id: "a",
          type: "audio",
          clips: [
            {
              id: "2",
              source: "footage/b.m4a",
              source_in: 0,
              source_out: 5,
              timeline_start: 0,
            },
          ],
        },
      ],
    };
    expect(timelinePlaybackQualityWarning(tl)).toMatch(/past the last video/);
  });
});
