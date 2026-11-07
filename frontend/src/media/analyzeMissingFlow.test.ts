import { describe, expect, it } from "vitest";
import {
  includeFrameCaptionsForChoice,
  namesToQueue,
  shouldShowAnalyzeMissingDialog,
} from "./analyzeMissingFlow";
import type { AnalysisEntry } from "./missingAnalysis";

describe("analyzeMissingFlow", () => {
  it("cancel queues nothing via includeFrameCaptions", () => {
    expect(includeFrameCaptionsForChoice("cancel")).toBeNull();
  });

  it("remembered choice skips the dialog when paid work exists", () => {
    expect(shouldShowAnalyzeMissingDialog("free_only", 2, 1)).toBe(false);
    expect(shouldShowAnalyzeMissingDialog(null, 2, 1)).toBe(true);
    expect(shouldShowAnalyzeMissingDialog(null, 0, 2)).toBe(false);
  });

  it("namesToQueue excludes caption-only gaps in free-only mode", () => {
    const entries: AnalysisEntry[] = [
      {
        id: "local.mp4",
        kind: "video",
        analysis: {
          merged_index: "not analyzed",
          ai_frame_captions: "not analyzed",
        },
      },
      {
        id: "captions_only.mp4",
        kind: "video",
        analysis: {
          merged_index: "complete",
          transcript: "complete",
          silences: "complete",
          audio_perception: "complete",
          takes: "complete",
          shots: "complete",
          video_perception: "complete",
          keyframes: "complete",
          ai_frame_captions: "not analyzed",
          waveform_peaks: { status: "complete" },
        },
      },
    ];
    expect(namesToQueue(entries, false)).toEqual(["local.mp4"]);
    expect(namesToQueue(entries, true)).toContain("captions_only.mp4");
  });
});
