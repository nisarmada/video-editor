import { describe, expect, it } from "vitest";
import { previewPunchInScale } from "./exportZoomPreview";

describe("previewPunchInScale", () => {
  it("returns 1 when zoom is omitted or at unity", () => {
    expect(previewPunchInScale(undefined)).toBe(1);
    expect(previewPunchInScale(1)).toBe(1);
    expect(previewPunchInScale(1.0005)).toBe(1);
  });

  it("returns zoom when above unity", () => {
    expect(previewPunchInScale(1.15)).toBe(1.15);
  });
});
