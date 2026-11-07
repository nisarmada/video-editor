import { describe, expect, it } from "vitest";
import type { TimelineV2 } from "./types";
import {
  buildClipLayoutRects,
  clipsInMarqueeRect,
  normalizeMarquee,
} from "./marqueeHitTest";

function sampleTl(): TimelineV2 {
  return {
    schema_version: 2,
    tracks: [
      {
        id: "v",
        type: "video",
        clips: [
          {
            id: "a",
            source: "x.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 0,
          },
          {
            id: "b",
            source: "y.mp4",
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
            source: "z.wav",
            source_in: 0,
            source_out: 2,
            timeline_start: 1,
          },
        ],
      },
      {
        id: "cap",
        type: "caption",
        clips: [
          {
            id: "cap1",
            text: "Hello captions",
            timeline_start: 0.5,
            source_in: 0,
            source_out: 2,
          },
        ],
      },
    ],
    settings: { fps: 30, clip_linking_enabled: false },
  };
}

describe("marqueeHitTest", () => {
  it("touch mode selects overlapping clips on multiple tracks", () => {
    const layout = buildClipLayoutRects(sampleTl(), 10);
    const a = layout.find((r) => r.clipId === "a")!;
    const c = layout.find((r) => r.clipId === "c")!;
    const box = normalizeMarquee(a.left, a.top, c.right, c.bottom);
    const ids = clipsInMarqueeRect(layout, box, "touch");
    expect(ids.sort()).toEqual(["a", "c"].sort());
  });

  it("inside mode requires full containment", () => {
    const layout = buildClipLayoutRects(sampleTl(), 10);
    const a = layout.find((r) => r.clipId === "a")!;
    const box = normalizeMarquee(a.left, a.top, a.right, a.bottom);
    const touch = clipsInMarqueeRect(layout, box, "touch");
    const inside = clipsInMarqueeRect(layout, box, "inside");
    expect(touch).toContain("a");
    expect(inside).toContain("a");
    const sliver = normalizeMarquee(a.left, a.top, a.left + 2, a.bottom);
    expect(clipsInMarqueeRect(layout, sliver, "inside")).not.toContain("a");
  });

  it("marquee selects caption clips on the caption row", () => {
    const layout = buildClipLayoutRects(sampleTl(), 10);
    const cap = layout.find((r) => r.clipId === "cap1")!;
    const box = normalizeMarquee(cap.left, cap.top, cap.right + 20, cap.bottom);
    expect(clipsInMarqueeRect(layout, box, "touch")).toContain("cap1");
  });

  it("off-DOM layout still includes far timeline clips", () => {
    const tl = sampleTl();
    tl.tracks[0]!.clips![1]!.timeline_start = 500;
    const layout = buildClipLayoutRects(tl, 10);
    const far = layout.find((r) => r.clipId === "b");
    expect(far?.left).toBeGreaterThan(4000);
    const box = normalizeMarquee(far!.left, far!.top, far!.right, far!.bottom);
    expect(clipsInMarqueeRect(layout, box, "touch")).toEqual(["b"]);
  });
});
