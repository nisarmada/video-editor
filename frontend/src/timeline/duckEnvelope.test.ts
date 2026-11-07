import { describe, expect, it } from "vitest";
import { duckFactorAt, duckFactorForTrack } from "./duckEnvelope";
import type { TimelineV2 } from "./types";

describe("duckFactorAt", () => {
  const windows = [{ start: 2, end: 4 }];

  it("stays full outside the overlap and ducked in the middle", () => {
    expect(duckFactorAt(1, windows, 0.25)).toBe(1);
    expect(duckFactorAt(4, windows, 0.25)).toBe(1);
    expect(duckFactorAt(3, windows, 0.25)).toBe(0.25);
    const attack = duckFactorAt(2.04, windows, 0.25);
    const release = duckFactorAt(3.875, windows, 0.25);
    expect(attack).toBeGreaterThan(0.25);
    expect(attack).toBeLessThan(1);
    expect(release).toBeGreaterThan(0.25);
    expect(release).toBeLessThan(1);
  });
});

describe("duckFactorForTrack", () => {
  it("uses the under track only while the playhead overlaps it", () => {
    const timeline: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "bed",
          type: "audio",
          duck_under_track_id: "speech",
          duck_gain: 0.25,
          clips: [],
        },
        {
          id: "speech",
          type: "audio",
          clips: [
            {
              id: "s1",
              source: "footage/take.wav",
              source_in: 0,
              source_out: 2,
              timeline_start: 2,
            },
          ],
        },
      ],
    };
    const bed = timeline.tracks[0];
    expect(duckFactorForTrack(timeline, bed, 1)).toBe(1);
    expect(duckFactorForTrack(timeline, bed, 3)).toBe(0.25);
  });
});
