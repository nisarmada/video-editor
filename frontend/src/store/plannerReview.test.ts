import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTimelineStore } from "./timelineStore";

describe("planner take review opt-in", () => {
  const origFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = origFetch;
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    useTimelineStore.setState({
      availablePlans: [],
      currentPlanName: "plan1",
      timeline: null,
      isDirty: false,
      plannerRunning: false,
      plannerPhase: "idle",
      plannerError: null,
      plannerTakeReviewGroups: null,
      _plannerPendingRun: null,
      selectedFootageNames: [],
    });
    vi.stubGlobal("confirm", () => true);
  });

  it("skips review state when reviewTakesFirst is false", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("/api/planner/estimate")) {
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              file_count: 1,
              omitted_count: 0,
              unanalyzed: [],
              input_tokens: 100,
              est_cost_usd: 0.01,
              confirm: false,
              model: "test",
              catalog_build_ms: 1,
              mode: "draft",
            }),
        };
      }
      if (url.includes("/api/planner/preflight-takes")) {
        throw new Error("preflight should not be called");
      }
      if (url.includes("/api/planner/run")) {
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              plan_name: "out.json",
              group_id: "g1",
              usage: {},
              timeline: { schema_version: 2, tracks: [] },
            }),
        };
      }
      if (url.includes("/api/plans")) {
        return { ok: true, json: async () => ({ plans: ["out"] }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    globalThis.fetch = fetchMock as typeof fetch;

    await useTimelineStore.getState().runPlannerJob("brief", "out", {
      reviewTakesFirst: false,
    });

    expect(useTimelineStore.getState().plannerPhase).not.toBe("review");
    expect(useTimelineStore.getState().plannerTakeReviewGroups).toBeNull();
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("preflight-takes"))).toBe(false);
  });

  it("opens review when reviewTakesFirst is true", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("/api/planner/estimate")) {
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              file_count: 1,
              omitted_count: 0,
              unanalyzed: [],
              input_tokens: 100,
              est_cost_usd: 0.01,
              confirm: false,
              model: "test",
              catalog_build_ms: 1,
              mode: "draft",
            }),
        };
      }
      if (url.includes("/api/planner/preflight-takes")) {
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              take_groups: [
                {
                  id: "g0",
                  source_file: "voice.m4a",
                  phrase_label: "hello",
                  attempts: [
                    {
                      id: "voice.m4a:0",
                      source_file: "voice.m4a",
                      take_index: 0,
                      text: "hi",
                      default_keep: true,
                    },
                  ],
                },
              ],
              group_count: 1,
            }),
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    await useTimelineStore.getState().runPlannerJob("brief", "out", {
      reviewTakesFirst: true,
    });

    expect(useTimelineStore.getState().plannerPhase).toBe("review");
    expect(useTimelineStore.getState().plannerTakeReviewGroups?.length).toBe(1);
    expect(useTimelineStore.getState().plannerRunning).toBe(false);
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("preflight-takes"))).toBe(true);
    expect(urls.some((u) => u.includes("/api/planner/run"))).toBe(false);
  });
});
