import { create } from "zustand";
import { fetchPlan, savePlan as savePlanToServer } from "../api/plans";
import { renderPlan as requestRender } from "../api/render";
import { applyTimelineOperation } from "../api/timelineOps";
import {
  canMutateTimeline,
  parseApplyOpErrorMessage,
  wrapUndoPayload,
} from "./timelineMutation";
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

/** Inverse operation payload returned by the backend after an edit. */
export type TimelineInverseOp = Record<string, unknown>;

export type SaveStatus = "idle" | "saving" | "saved" | "error";
export type RenderStatus = "idle" | "rendering" | "done" | "error";

type TimelineViewState = {
  /** Active plan stem (no .json); persisted file is `{currentPlanName}.json`. */
  currentPlanName: string;
  /** Authoritative v2 timeline from the server after load or applyOperation. */
  timeline: TimelineV2 | null;
  timelineLoading: boolean;
  timelineError: string | null;

  /** True after local edits vs last load/save (apply-op / undo / redo). */
  isDirty: boolean;
  saveStatus: SaveStatus;
  saveError: string | null;

  renderStatus: RenderStatus;
  renderError: string | null;
  /** Basename of last successful export (e.g. `draft1_v2_export.mp4`). */
  outputName: string | null;
  outputDownloadUrl: string | null;

  playheadSeconds: number;
  pxPerSecond: number;
  timelinePlaying: boolean;

  /** Selected clip on the timeline (UI); not necessarily validated server-side. */
  selectedClipId: string | null;

  /** Block concurrent apply while a mutation request is in flight. */
  applyOperationInProgress: boolean;
  /** Future: clip drag trim/move — block mutations while true. */
  dragInProgress: boolean;

  undoStack: TimelineInverseOp[];
  redoStack: TimelineInverseOp[];

  /** Short message when backend rejects apply or undo/redo. */
  opErrorMessage: string | null;

  loadTimeline: (name?: string) => Promise<void>;
  /** PUT current timeline to server; clears dirty on success. */
  savePlan: () => Promise<void>;
  /** Save if dirty, then POST /api/render using plan file on disk. */
  exportPlan: () => Promise<void>;
  setPlayheadSeconds: (t: number) => void;
  setPxPerSecond: (pps: number) => void;
  setTimelinePlaying: (playing: boolean) => void;
  toggleTimelinePlaying: () => void;
  setSelectedClipId: (id: string | null) => void;
  setDragInProgress: (v: boolean) => void;
  clearOpError: () => void;

  /**
   * All timeline edits go through this: POST /api/timeline/apply-op, replace `timeline`
   * with the response body’s `timeline`. Pushes returned inverse to `undoStack`, clears `redoStack`.
   * Returns the inverse op.
   */
  applyOperation: (op: TimelineEditOp) => Promise<TimelineInverseOp>;

  /** Pop undo stack, run inverse via apply_undo on backend, push returned inverse to redo. */
  undo: () => Promise<void>;

  /** Pop redo stack, run via apply_undo, push returned inverse to undo. */
  redo: () => Promise<void>;

  /** Split selected clip at current playhead (delegates to applyOperation). */
  splitAtPlayhead: () => Promise<TimelineInverseOp>;

  /** Delete selected clip (delegates to applyOperation). */
  deleteSelectedClip: () => Promise<TimelineInverseOp>;
};

/**
 * Raw POST without undo/redo bookkeeping — used internally and for tests.
 */
async function fetchApplyOp(
  timeline: TimelineV2,
  operation: string,
  argumentsObj: Record<string, unknown>,
) {
  return applyTimelineOperation(timeline, operation, argumentsObj);
}

export const useTimelineStore = create<TimelineViewState>((set, get) => ({
  currentPlanName: DEFAULT_PLAN_NAME,
  timeline: null,
  timelineLoading: false,
  timelineError: null,
  isDirty: false,
  saveStatus: "idle",
  saveError: null,
  renderStatus: "idle",
  renderError: null,
  outputName: null,
  outputDownloadUrl: null,
  playheadSeconds: 0,
  pxPerSecond: DEFAULT_PX_PER_SEC,
  timelinePlaying: false,
  selectedClipId: null,
  applyOperationInProgress: false,
  dragInProgress: false,
  undoStack: [],
  redoStack: [],
  opErrorMessage: null,

  loadTimeline: async (name) => {
    const currentPlanName = name ?? get().currentPlanName;
    set({
      timelineLoading: true,
      timelineError: null,
      currentPlanName,
      saveStatus: "idle",
      saveError: null,
      renderStatus: "idle",
      renderError: null,
      outputName: null,
      outputDownloadUrl: null,
    });
    try {
      const timeline = await fetchPlan(currentPlanName);
      set({
        timeline,
        timelineLoading: false,
        isDirty: false,
        playheadSeconds: 0,
        timelinePlaying: false,
        selectedClipId: null,
        undoStack: [],
        redoStack: [],
        opErrorMessage: null,
        renderStatus: "idle",
        renderError: null,
        outputName: null,
        outputDownloadUrl: null,
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      set({ timelineLoading: false, timelineError: message });
    }
  },

  savePlan: async () => {
    const { timeline, currentPlanName, saveStatus } = get();
    if (!timeline || saveStatus === "saving") return;
    set({ saveStatus: "saving", saveError: null });
    try {
      await savePlanToServer(currentPlanName, timeline);
      set({ isDirty: false, saveStatus: "saved", saveError: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      set({ saveStatus: "error", saveError: msg });
    }
  },

  exportPlan: async () => {
    const s0 = get();
    if (!s0.timeline || s0.timelineLoading || s0.renderStatus === "rendering") {
      return;
    }
    set({
      renderStatus: "rendering",
      renderError: null,
      outputName: null,
      outputDownloadUrl: null,
    });
    try {
      if (s0.isDirty) {
        const tl = get().timeline;
        const name = get().currentPlanName;
        if (!tl) {
          set({ renderStatus: "error", renderError: "No timeline to save" });
          return;
        }
        try {
          await savePlanToServer(name, tl);
          set({
            isDirty: false,
            saveStatus: "saved",
            saveError: null,
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : "Save failed";
          set({
            saveStatus: "error",
            saveError: msg,
            renderStatus: "error",
            renderError: `Save before export failed: ${msg}`,
          });
          return;
        }
      }
      const { currentPlanName } = get();
      const outputStem = `${currentPlanName.replace(/\.json$/i, "")}_export`;
      const result = await requestRender({
        plan_name: currentPlanName,
        output: outputStem,
      });
      const basename = result.output.split(/[/\\]/).pop() ?? result.output;
      set({
        renderStatus: "done",
        renderError: null,
        outputName: basename,
        outputDownloadUrl: result.url,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Render failed";
      set({ renderStatus: "error", renderError: msg });
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
  setDragInProgress: (v) => set({ dragInProgress: v }),
  clearOpError: () => set({ opErrorMessage: null }),

  applyOperation: async (op) => {
    const { timeline } = get();
    if (!timeline) {
      throw new Error("No timeline loaded");
    }
    if (!canMutateTimeline(get())) {
      throw new Error("Timeline mutation blocked");
    }
    set({ applyOperationInProgress: true, opErrorMessage: null });
    try {
      const result = await fetchApplyOp(timeline, op.operation, op.arguments ?? {});
      set((s) => ({
        timeline: result.timeline,
        undoStack: [...s.undoStack, result.undo],
        redoStack: [],
        isDirty: true,
        saveStatus: "idle",
        saveError: null,
      }));
      return result.undo;
    } catch (e) {
      const msg =
        e instanceof Error ? parseApplyOpErrorMessage(e.message) : "Request failed";
      set({ opErrorMessage: msg });
      throw e;
    } finally {
      set({ applyOperationInProgress: false });
    }
  },

  undo: async () => {
    const s = get();
    if (!s.timeline || s.undoStack.length === 0) return;
    if (!canMutateTimeline(s)) return;
    const inverse = s.undoStack[s.undoStack.length - 1];
    set({ applyOperationInProgress: true, opErrorMessage: null });
    try {
      const result = await fetchApplyOp(
        s.timeline,
        "apply_undo",
        wrapUndoPayload(inverse),
      );
      set({
        timeline: result.timeline,
        undoStack: s.undoStack.slice(0, -1),
        redoStack: [...s.redoStack, result.undo],
        isDirty: true,
        saveStatus: "idle",
        saveError: null,
      });
    } catch (e) {
      const msg =
        e instanceof Error ? parseApplyOpErrorMessage(e.message) : "Undo failed";
      set({ opErrorMessage: msg });
    } finally {
      set({ applyOperationInProgress: false });
    }
  },

  redo: async () => {
    const s = get();
    if (!s.timeline || s.redoStack.length === 0) return;
    if (!canMutateTimeline(s)) return;
    const inverse = s.redoStack[s.redoStack.length - 1];
    set({ applyOperationInProgress: true, opErrorMessage: null });
    try {
      const result = await fetchApplyOp(
        s.timeline,
        "apply_undo",
        wrapUndoPayload(inverse),
      );
      set({
        timeline: result.timeline,
        redoStack: s.redoStack.slice(0, -1),
        undoStack: [...s.undoStack, result.undo],
        isDirty: true,
        saveStatus: "idle",
        saveError: null,
      });
    } catch (e) {
      const msg =
        e instanceof Error ? parseApplyOpErrorMessage(e.message) : "Redo failed";
      set({ opErrorMessage: msg });
    } finally {
      set({ applyOperationInProgress: false });
    }
  },

  splitAtPlayhead: async () => {
    const { selectedClipId, playheadSeconds } = get();
    if (!selectedClipId) {
      throw new Error("No clip selected");
    }
    return get().applyOperation({
      operation: "split_clip",
      arguments: {
        clip_id: selectedClipId,
        at_timeline_time: playheadSeconds,
      },
    });
  },

  deleteSelectedClip: async () => {
    const id = get().selectedClipId;
    if (!id) {
      throw new Error("No clip selected");
    }
    const undo = await get().applyOperation({
      operation: "delete_clip",
      arguments: { clip_id: id },
    });
    set({ selectedClipId: null });
    return undo;
  },
}));
