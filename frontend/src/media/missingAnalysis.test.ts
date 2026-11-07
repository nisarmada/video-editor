import { describe, expect, it } from "vitest";
import { filesMissingAnalysis, missingAnalysisFields } from "./missingAnalysis";

describe("missingAnalysisFields", () => {
  it("ignores fields that do not apply to audio files", () => {
    expect(
      missingAnalysisFields({
        id: "take.wav",
        kind: "audio",
        analysis: {
          merged_index: "complete",
          transcript: "not analyzed",
          silences: "complete",
          audio_perception: "not analyzed",
          takes: "not analyzed",
          shots: "not analyzed",
          waveform_peaks: { status: "complete" },
        },
      }),
    ).toEqual(["transcript", "audio_perception", "takes"]);
  });

  it("lists every incomplete video field", () => {
    const rows = filesMissingAnalysis([
      {
        id: "ready.mp4",
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
          ai_frame_captions: "complete",
          waveform_peaks: { status: "complete" },
        },
      },
      {
        id: "new.mp4",
        kind: "video",
        analysis: {
          merged_index: "not analyzed",
          transcript: "complete",
          silences: "not analyzed",
          audio_perception: "not analyzed",
          takes: "not analyzed",
          shots: "not analyzed",
          video_perception: "not analyzed",
          keyframes: "not analyzed",
          ai_frame_captions: "not analyzed",
          waveform_peaks: { status: "complete" },
        },
      },
    ]);
    expect(rows.map((row) => row.id)).toEqual(["new.mp4"]);
    expect(rows[0].missing).toContain("merged_index");
    expect(rows[0].missing).not.toContain("transcript");
  });
});
