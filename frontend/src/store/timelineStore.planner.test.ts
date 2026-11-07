import { describe, expect, it } from "vitest";
import { timelineCanPersist } from "./timelineStore";
import type { TimelineV2 } from "../timeline/types";

describe("timelineCanPersist", () => {
  it("rejects empty video track", () => {
    const tl: TimelineV2 = {
      schema_version: 2,
      tracks: [
        { id: "v", type: "video", clips: [] },
        { id: "a", type: "audio", clips: [] },
      ],
    };
    expect(timelineCanPersist(tl)).toBe(false);
  });

  it("accepts at least one video clip", () => {
    const tl: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "v",
          type: "video",
          clips: [
            {
              id: "c1",
              source: "footage/x.mp4",
              source_in: 0,
              source_out: 1,
              timeline_start: 0,
            },
          ],
        },
      ],
    };
    expect(timelineCanPersist(tl)).toBe(true);
  });
});
