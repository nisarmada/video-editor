import { create } from "zustand";
import { fetchPlan } from "../api/plans";
import type { TimelineV2 } from "../timeline/types";

export const DEFAULT_PLAN_NAME = "draft1_v2";

export const MIN_PX_PER_SEC = 24;
export const MAX_PX_PER_SEC = 160;
export const DEFAULT_PX_PER_SEC = 48;

type TimelineViewState = {
  planName: string;
  timeline: TimelineV2 | null;
  timelineLoading: boolean;
  timelineError: string | null;
  playheadSeconds: number;
  pxPerSecond: number;

  loadTimeline: (name?: string) => Promise<void>;
  setPlayheadSeconds: (t: number) => void;
  setPxPerSecond: (pps: number) => void;
};

export const useTimelineStore = create<TimelineViewState>((set, get) => ({
  planName: DEFAULT_PLAN_NAME,
  timeline: null,
  timelineLoading: false,
  timelineError: null,
  playheadSeconds: 0,
  pxPerSecond: DEFAULT_PX_PER_SEC,

  loadTimeline: async (name) => {
    const planName = name ?? get().planName;
    set({ timelineLoading: true, timelineError: null, planName });
    try {
      const timeline = await fetchPlan(planName);
      set({
        timeline,
        timelineLoading: false,
        playheadSeconds: 0,
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      set({ timelineLoading: false, timelineError: message });
    }
  },

  setPlayheadSeconds: (t) => set({ playheadSeconds: Math.max(0, t) }),
  setPxPerSecond: (pps) =>
    set({
      pxPerSecond: Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, pps)),
    }),
}));
