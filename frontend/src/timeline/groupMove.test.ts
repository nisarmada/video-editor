import { describe, expect, it } from "vitest";
import type { TimelineV2 } from "./types";
import { validateGroupMove } from "./groupMove";

function tlTight(): TimelineV2 {
  return {
    schema_version: 2,
    tracks: [
      {
        id: "v",
        type: "video",
        clips: [
          {
            id: "a",
            source: "a.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 0,
          },
          {
            id: "b",
            source: "b.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 2.1,
          },
        ],
      },
      { id: "au", type: "audio", clips: [] },
    ],
    settings: { fps: 30 },
  };
}

function tl(): TimelineV2 {
  return {
    schema_version: 2,
    tracks: [
      {
        id: "v",
        type: "video",
        clips: [
          {
            id: "a",
            source: "a.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 0,
          },
          {
            id: "b",
            source: "b.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 3,
          },
        ],
      },
      {
        id: "au",
        type: "audio",
        clips: [
          {
            id: "c",
            source: "c.wav",
            source_in: 0,
            source_out: 2,
            timeline_start: 5,
          },
        ],
      },
    ],
    settings: { fps: 30 },
  };
}

describe("validateGroupMove", () => {
  it("preserves relative offsets", () => {
    const r = validateGroupMove(tl(), ["a", "c"], 1);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const a = r.moves.find((m) => m.clipId === "a")!;
    const c = r.moves.find((m) => m.clipId === "c")!;
    expect(a.newStart).toBe(1);
    expect(c.newStart).toBe(6);
  });

  it("rejects overlap on same track", () => {
    const r = validateGroupMove(tlTight(), ["a", "b"], -0.2);
    expect(r.ok).toBe(false);
  });

  it("rejects before zero", () => {
    const r = validateGroupMove(tl(), ["a"], -1);
    expect(r.ok).toBe(false);
  });
});
