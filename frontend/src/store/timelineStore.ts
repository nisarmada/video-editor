import { create } from "zustand";
import { fetchPlan } from "../api/plans";
import {
  applyTimelineOperation,
  type ApplyOpResult,
} from "../api/timelineOps";
import type { TimelineV2 } from "../timeline/types";

export const DEFAULT_PLAN_NAME = "draft1_v2";

export const MIN_PX_PER_SEC = 24;
export const MAX_PX_PER_SEC = 160;
export const DEFAULT_PX_PER_SEC = 48;

/** Single op for applyOperation — matches backend dispatch_operation / timeline_ops. */
export type TimelineEditOp = {
  operation: string;
  arguments?: Record<string, unknown>;
};

type TimelineViewState = {
  planName: string;
  /** Authoritative v2 timeline from the server after load or applyOperation. */
  timeline: TimelineV2 | null;
  timelineLoading: boolean;
  timelineError: string | null;

  playheadSeconds: number;
  pxPerSecond: number;
  timelinePlaying: boolean;

  /** Selected clip on the timeline (UI); not necessarily validated server-side. */
  selectedClipId: string | null;

  loadTimeline: (name?: string) => Promise<void>;
  setPlayheadSeconds: (t: number) => void;
  setPxPerSecond: (pps: number) => void;
  setTimelinePlaying: (playing: boolean) => void;
  toggleTimelinePlaying: () => void;
  setSelectedClipId: (id: string | null) => void;

  /**
   * All timeline mutations (future: trim, split, planner merge, undo/redo)
   * should call this: POST /api/timeline/apply-op, then replace `timeline` with the response.
   * Returns `{ timeline, undo }` for undo stacks and Claude flows.
   */
  applyOperation: (op: TimelineEditOp) => Promise<ApplyOpResult>;
};

export const useTimelineStore = create<TimelineViewState>((set, get) => ({
  planName: DEFAULT_PLAN_NAME,
  timeline: null,
  timelineLoading: false,
  timelineError: null,
  playheadSeconds: 0,
  pxPerSecond: DEFAULT_PX_PER_SEC,
  timelinePlaying: false,
  selectedClipId: null,

  loadTimeline: async (name) => {
    const planName = name ?? get().planName;
    set({ timelineLoading: true, timelineError: null, planName });
    try {
      const timeline = await fetchPlan(planName);
      set({
        timeline,
        timelineLoading: false,
        playheadSeconds: 0,
        timelinePlaying: false,
        selectedClipId: null,
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
  setTimelinePlaying: (playing) => set({ timelinePlaying: playing }),
  toggleTimelinePlaying: () =>
    set((s) => ({ timelinePlaying: !s.timelinePlaying })),
  setSelectedClipId: (id) => set({ selectedClipId: id }),

  applyOperation: async (op) => {
    const { timeline } = get();
    if (!timeline) {
      throw new Error("No timeline loaded");
    }
    const result = await applyTimelineOperation(
      timeline,
      op.operation,
      op.arguments ?? {},
    );
    set({ timeline: result.timeline });
    return result;
  },
}));
