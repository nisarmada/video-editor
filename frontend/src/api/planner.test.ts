import { describe, expect, it } from "vitest";
import {
  formatPlannerEstimate,
  formatPlannerEstimateNotes,
  formatTokenCount,
} from "./planner";

describe("planner estimate line", () => {
  it("matches the planner bar wording", () => {
    expect(formatTokenCount(9000)).toBe("~9k");
    expect(
      formatPlannerEstimate({
        file_count: 6,
        omitted_count: 0,
        unanalyzed: [],
        input_tokens: 9000,
        est_cost_usd: 0.04,
        confirm: false,
        model: "claude-sonnet-5-5",
        catalog_build_ms: 1,
        mode: "draft",
      }),
    ).toBe("6 files, ~9k input tokens, est. $0.04");
  });

  it("notes omitted count and unanalyzed names", () => {
    expect(
      formatPlannerEstimateNotes({
        file_count: 2,
        omitted_count: 3,
        unanalyzed: ["raw.mov"],
        input_tokens: 1000,
        est_cost_usd: 0.01,
        confirm: false,
        model: "x",
        catalog_build_ms: 1,
        mode: "draft",
      }),
    ).toEqual([
      "3 analyzed file(s) omitted from the catalog (token budget)",
      "Excluded (no merged index): raw.mov",
    ]);
  });
});
