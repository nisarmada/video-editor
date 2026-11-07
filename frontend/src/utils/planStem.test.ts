import { describe, expect, it } from "vitest";
import { nextAutoPlanStem } from "./planStem";

describe("nextAutoPlanStem", () => {
  it("picks the first unused plan-N name", () => {
    expect(nextAutoPlanStem([])).toBe("plan-1");
    expect(nextAutoPlanStem(["plan-1", "plan-2.json"])).toBe("plan-3");
  });
});
