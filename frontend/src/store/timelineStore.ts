import { create } from "zustand";
import {
  fetchFootageList,
  rescanFootageFolder,
  type FootageClip,
} from "../api/footage";
import {
  fetchPlan,
  fetchPlanList,
  savePlan as savePlanToServer,
} from "../api/plans";
import { runPlanner as callPlanner } from "../api/planner";
import {
  cancelRenderJob,
  getRenderJob,
  startRender,
  type RenderJobPublic,
} from "../api/render";
import { fetchSettings } from "../api/settings";
import { revealOutputFolder } from "../api/desktop";
import {
  deletePlan as deletePlanApi,
  duplicatePlan as duplicatePlanApi,
  renamePlan as renamePlanApi,
} from "../api/planManagement";
import { applyTimelineOperation } from "../api/timelineOps";
import { LAST_OPENED_PLAN_KEY, normalizePlanStem, validatePlanStem } from "../utils/planStem";
import {
  canMutateTimeline,
  parseApplyOpErrorMessage,
  wrapUndoPayload,
} from "./timelineMutation";
import type { CaptionStyle, TimelineV2 } from "../timeline/types";

export const DEFAULT_PLAN_NAME = "draft1_v2";

export const MIN_PX_PER_SEC = 24;
export const MAX_PX_PER_SEC = 160;
export const DEFAULT_PX_PER_SEC = 48;

/** One clip on video + empty audio/caption; passes validate_v2_data (scripts/timeline_format.py). */
const DEFAULT_CAPTION_STYLE: CaptionStyle = { preset: "bold_pop" };

function ensureCaptionStyle(tl: TimelineV2): TimelineV2 {
  const s = tl.settings ?? {};
  let next = tl;
  if (!s.caption_style) {
    next = {
      ...next,
      settings: { ...(next.settings ?? {}), caption_style: { ...DEFAULT_CAPTION_STYLE } },
    };
  }
  const s2 = next.settings ?? {};
  if (s2.clip_linking_enabled === undefined) {
    next = {
      ...next,
      settings: { ...s2, clip_linking_enabled: true },
    };
  }
  return next;
}

export function newEmptyTimelineV2(): TimelineV2 {
  return {
    schema_version: 2,
    tracks: [
      {
        id: "track-video-main",
        type: "video",
        label: "Video",
        clips: [
          {
            id: crypto.randomUUID(),
            source: "footage/test_a.mp4",
            source_in: 0,
            source_out: 1,
            timeline_start: 0,
            created_by: "user",
          },
        ],
      },
      { id: "track-audio-main", type: "audio", label: "Audio", clips: [] },
      { id: "track-caption-main", type: "caption", label: "Captions", clips: [] },
    ],
    settings: {
      width: 1080,
      height: 1920,
      fps: 30,
      clip_linking_enabled: true,
      caption_style: { ...DEFAULT_CAPTION_STYLE },
    },
  };
}

/** Single op for applyOperation — matches backend dispatch_operation / timeline_ops. */
export type TimelineEditOp = {
  operation: string;
  arguments?: Record<string, unknown>;
};

/** Inverse operation payload returned by the backend after an edit. */
export type TimelineInverseOp = Record<string, unknown>;

export type SaveStatus = "idle" | "saving" | "saved" | "error";
export type RenderStatus = "idle" | "rendering" | "done" | "error";

/** Upper preview panel: timeline (video track) vs source file from media bin. */
export type PreviewPanelMode = "timeline" | "source";

type TimelineViewState = {
  /** Active plan stem (no .json); persisted file is `{currentPlanName}.json`. */
  currentPlanName: string;
  /** Stems from GET /api/plans (no .json). */
  availablePlans: string[];
  /** User-visible message when listing plans failed or none exist. */
  plansListError: string | null;

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
  /** Background render job (polls GET /api/render/{id}). */
  renderJobId: string | null;
  renderJob: RenderJobPublic | null;
  renderLogVisible: boolean;

  /** Cross-cutting API errors (non-blocking toast line). */
  uiBannerError: string | null;

  playheadSeconds: number;
  pxPerSecond: number;
  timelinePlaying: boolean;

  /** Selected clip on the timeline (UI); not necessarily validated server-side. */
  selectedClipId: string | null;
  /** Multi-select (shift-click). `selectedClipId` stays the primary (last clicked). */
  selectedClipIds: string[];

  /** Selected item in the media bin (footage filename stem). */
  selectedFootageName: string | null;
  footageClips: FootageClip[];
  footageLoading: boolean;
  footageError: string | null;

  /** Which preview is shown — only one player mounts at a time. */
  previewPanelMode: PreviewPanelMode;

  /** Timeline caption overlay: limit ASS to selected clip (preview only). */
  captionPreviewClipOnly: boolean;
  setCaptionPreviewClipOnly: (v: boolean) => void;

  /** Draw TikTok/Reels-style safe margins on the main preview. */
  captionSafeAreaGuide: boolean;
  setCaptionSafeAreaGuide: (v: boolean) => void;

  /** Block concurrent apply while a mutation request is in flight. */
  applyOperationInProgress: boolean;
  /** Future: clip drag trim/move — block mutations while true. */
  dragInProgress: boolean;

  undoStack: TimelineInverseOp[];
  redoStack: TimelineInverseOp[];

  /** Short message when backend rejects apply or undo/redo. */
  opErrorMessage: string | null;
  /** Ephemeral hint for keyboard shortcuts (no-op, split refused, etc.). */
  shortcutToast: string | null;

  /** POST /api/planner/run in flight. */
  plannerRunning: boolean;
  plannerError: string | null;

  /** Apply local caption style edits (commits via applyOperation set_timeline_settings). */
  setCaptionStyleDraft: (style: CaptionStyle) => void;
  /** Set per-clip style override draft (commits via set_clip_property). */
  setClipStyleOverrideDraft: (clipId: string, style: Partial<CaptionStyle> | null) => void;

  /** Fetches plan list, opens last opened / first plan (or DEFAULT_PLAN_NAME fallback). */
  initSession: () => Promise<void>;
  /** Refetch GET /api/plans (e.g. after planner writes a new file). */
  refreshAvailablePlans: () => Promise<void>;
  /** Load plan by stem; optional name reloads current. Confirms if dirty (unless skipDirtyConfirm). */
  loadPlan: (
    name?: string,
    opts?: { skipDirtyConfirm?: boolean },
  ) => Promise<void>;
  /** PUT current timeline to server; clears dirty on success. */
  savePlan: () => Promise<void>;
  /** Prompt for stem, PUT empty valid v2, refresh list, load. */
  createNewPlan: () => Promise<void>;
  /** Run AI planner; on success refresh list and load the saved file (skip dirty confirm). */
  runPlannerJob: (brief: string, saveAsStem: string) => Promise<void>;
  /** Save if dirty, then POST /api/render using plan file on disk. */
  exportPlan: () => Promise<void>;
  cancelExport: () => Promise<void>;
  setRenderLogVisible: (v: boolean) => void;
  revealOutputInFinder: () => Promise<void>;
  clearUiBanner: () => void;
  setUiBannerError: (msg: string | null) => void;

  /** Plan file ops (picker); blocks while a render is running. */
  renamePlanFile: (fromStem: string, toStem: string) => Promise<void>;
  duplicatePlanFile: (fromStem: string, toStem: string) => Promise<void>;
  deletePlanFile: (stem: string) => Promise<void>;

  setPlayheadSeconds: (t: number) => void;
  setPxPerSecond: (pps: number) => void;
  setTimelinePlaying: (playing: boolean) => void;
  toggleTimelinePlaying: () => void;
  setSelectedClipId: (id: string | null) => void;
  setSelectedClipIds: (ids: string[]) => void;
  setDragInProgress: (v: boolean) => void;
  clearOpError: () => void;
  setShortcutToast: (msg: string | null) => void;

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

  /** Detach embedded audio to audio track (video clip only). */
  separateAudio: () => Promise<TimelineInverseOp | void>;
  /** Merge paired audio back into video (selected video or linked audio clip). */
  reattachAudio: () => Promise<TimelineInverseOp | void>;
  /** Clear group_id on selected clip and its linked partner. */
  unlinkClipsAction: () => Promise<TimelineInverseOp | void>;
  /** Flip settings.clip_linking_enabled. */
  toggleClipLinking: () => Promise<TimelineInverseOp | void>;
  /** Toggle muted on the track that contains the selected clip (video/audio only). */
  toggleSelectedTrackMute: () => Promise<TimelineInverseOp | void>;
  /** Split many clips at one timeline time — single undo step via batch_operations. */
  splitClipsAtTime: (clipIds: string[], atTimelineTime: number) => Promise<TimelineInverseOp>;
  deleteClipsByIds: (clipIds: string[]) => Promise<TimelineInverseOp>;
  separateAudioForClip: (clipId: string) => Promise<TimelineInverseOp | void>;
  reattachAudioForClip: (clipId: string) => Promise<TimelineInverseOp | void>;
  unlinkClipsForClip: (clipId: string) => Promise<TimelineInverseOp | void>;
  toggleTrackMuteById: (trackId: string) => Promise<TimelineInverseOp | void>;
  toggleTrackLockById: (trackId: string) => Promise<TimelineInverseOp | void>;
  muteClipToggleById: (clipId: string) => Promise<TimelineInverseOp | void>;
  trimTimelineEdge: (
    clipId: string,
    edge: "start" | "end",
    atTimelineTime: number,
  ) => Promise<TimelineInverseOp>;

  /** List footage from server. Pass `{ silent: true }` to refresh without clearing the list (polling). */
  fetchFootage: (opts?: { silent?: boolean }) => Promise<void>;
  rescanFootage: () => Promise<void>;
  selectFootage: (name: string) => void;
  setPreviewPanelMode: (mode: PreviewPanelMode) => void;
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
  currentPlanName: "",
  availablePlans: [],
  plansListError: null,
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
  renderJobId: null,
  renderJob: null,
  renderLogVisible: false,
  uiBannerError: null,
  playheadSeconds: 0,
  pxPerSecond: DEFAULT_PX_PER_SEC,
  timelinePlaying: false,
  selectedClipId: null,
  selectedClipIds: [],
  selectedFootageName: null,
  footageClips: [],
  footageLoading: false,
  footageError: null,
  previewPanelMode: "timeline",
  captionPreviewClipOnly: false,
  setCaptionPreviewClipOnly: (v) => set({ captionPreviewClipOnly: v }),
  captionSafeAreaGuide: false,
  setCaptionSafeAreaGuide: (v) => set({ captionSafeAreaGuide: v }),
  applyOperationInProgress: false,
  dragInProgress: false,
  undoStack: [],
  redoStack: [],
  opErrorMessage: null,
  shortcutToast: null,
  plannerRunning: false,
  plannerError: null,

  fetchFootage: async (opts) => {
    const silent = opts?.silent ?? false;
    if (!silent) {
      set({ footageLoading: true, footageError: null });
    }
    try {
      const clips = await fetchFootageList();
      set((s) => ({
        footageClips: clips,
        footageLoading: silent ? s.footageLoading : false,
        footageError: silent ? s.footageError : null,
      }));
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      if (!silent) {
        set({ footageLoading: false, footageError: message });
      }
    }
  },

  rescanFootage: async () => {
    set({ footageError: null });
    try {
      await rescanFootageFolder();
      await get().fetchFootage({ silent: true });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Rescan failed";
      set({ footageError: message });
    }
  },

  selectFootage: (name) =>
    set({
      selectedFootageName: name,
      previewPanelMode: "source",
      timelinePlaying: false,
    }),

  setPreviewPanelMode: (mode) =>
    set({
      previewPanelMode: mode,
      ...(mode === "source" ? { timelinePlaying: false } : {}),
    }),

  refreshAvailablePlans: async () => {
    try {
      const list = await fetchPlanList();
      set({ availablePlans: list, plansListError: null });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to list plans";
      set({ plansListError: message });
    }
  },

  initSession: async () => {
    set({
      plansListError: null,
      timelineLoading: true,
      timelineError: null,
    });
    try {
      const list = await fetchPlanList();
      if (list.length === 0) {
        try {
          await get().loadPlan(DEFAULT_PLAN_NAME, { skipDirtyConfirm: true });
          set({
            availablePlans: [DEFAULT_PLAN_NAME],
            plansListError: null,
          });
        } catch {
          set({
            availablePlans: [],
            plansListError:
              "No plan files in plans/. Add a JSON file or create one with New plan.",
            timelineLoading: false,
            timeline: null,
            timelineError: null,
            currentPlanName: "",
            saveStatus: "idle",
            saveError: null,
            renderStatus: "idle",
            renderError: null,
            outputName: null,
            outputDownloadUrl: null,
            renderJobId: null,
            renderJob: null,
            renderLogVisible: false,
          });
        }
        return;
      }
      set({ availablePlans: list, plansListError: null });
      const stored =
        typeof localStorage !== "undefined"
          ? localStorage.getItem(LAST_OPENED_PLAN_KEY)
          : null;
      const stem =
        stored && list.includes(stored) ? stored : list[0];
      await get().loadPlan(stem, { skipDirtyConfirm: true });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to list plans";
      set({
        plansListError: message,
        availablePlans: [],
        timelineLoading: false,
        timeline: null,
        timelineError: message,
        currentPlanName: "",
      });
    }
  },

  loadPlan: async (name, opts) => {
    const raw = name ?? get().currentPlanName;
    const target = normalizePlanStem(raw);
    if (!target) {
      set({ timelineError: "No plan selected.", timelineLoading: false });
      return;
    }
    if (!opts?.skipDirtyConfirm && get().isDirty) {
      if (
        typeof window !== "undefined" &&
        !window.confirm("Discard unsaved changes?")
      ) {
        return;
      }
    }
    set({
      timelineLoading: true,
      timelineError: null,
      currentPlanName: target,
      saveStatus: "idle",
      saveError: null,
      renderStatus: "idle",
      renderError: null,
      outputName: null,
      outputDownloadUrl: null,
      renderJobId: null,
      renderJob: null,
      renderLogVisible: false,
    });
    try {
      const timeline = ensureCaptionStyle(await fetchPlan(target));
      if (typeof localStorage !== "undefined") {
        localStorage.setItem(LAST_OPENED_PLAN_KEY, target);
      }
      set({
        timeline,
        timelineLoading: false,
        isDirty: false,
        playheadSeconds: 0,
        timelinePlaying: false,
        selectedClipId: null,
        selectedClipIds: [],
        previewPanelMode: "timeline",
        undoStack: [],
        redoStack: [],
        opErrorMessage: null,
        renderStatus: "idle",
        renderError: null,
        outputName: null,
        outputDownloadUrl: null,
        renderJobId: null,
        renderJob: null,
        renderLogVisible: false,
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

  createNewPlan: async () => {
    if (typeof window === "undefined") return;
    const raw = window.prompt("New plan name (no .json):");
    if (raw === null) return;
    const stemErr = validatePlanStem(raw);
    if (stemErr) {
      window.alert(stemErr);
      return;
    }
    const stem = normalizePlanStem(raw);
    if (get().isDirty) {
      if (!window.confirm("Discard unsaved changes?")) return;
    }
    set({ timelineLoading: true, timelineError: null, opErrorMessage: null });
    try {
      const tl = newEmptyTimelineV2();
      await savePlanToServer(stem, tl);
      let list = get().availablePlans;
      try {
        list = await fetchPlanList();
      } catch {
        list = [...new Set([...get().availablePlans, stem])].sort();
      }
      set({ availablePlans: list, plansListError: null });
      await get().loadPlan(stem, { skipDirtyConfirm: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to create plan";
      set({ timelineLoading: false, timelineError: msg });
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
      renderJobId: null,
      renderJob: null,
      uiBannerError: null,
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
      let settings;
      try {
        settings = await fetchSettings();
      } catch {
        settings = {
          render_defaults: { captions: false, max_length: null },
        };
      }
      const rd = settings.render_defaults;
      const { job_id: jobId } = await startRender({
        plan_name: currentPlanName,
        output: outputStem,
        captions: rd.captions,
        max_length: rd.max_length,
      });

      set({ renderJobId: jobId });

      for (;;) {
        const j = await getRenderJob(jobId);
        set({ renderJob: j });
        if (j.state === "done") {
          const basename =
            (j.output && j.output.split(/[/\\]/).pop()) || `${outputStem}.mp4`;
          set({
            renderStatus: "done",
            renderError: null,
            outputName: basename,
            outputDownloadUrl: j.url,
            renderJobId: jobId,
          });
          break;
        }
        if (j.state === "failed" || j.state === "cancelled") {
          const msg =
            j.state === "cancelled"
              ? "Export cancelled."
              : j.error || "Render failed";
          set({
            renderStatus: "error",
            renderError: msg,
            renderJobId: jobId,
          });
          break;
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Render failed";
      set({
        renderStatus: "error",
        renderError: msg,
        uiBannerError: msg,
      });
    }
  },

  cancelExport: async () => {
    const id = get().renderJobId;
    if (!id) return;
    try {
      await cancelRenderJob(id);
      set({ uiBannerError: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Cancel failed";
      set({ uiBannerError: msg });
    }
  },

  setRenderLogVisible: (v) => set({ renderLogVisible: v }),

  revealOutputInFinder: async () => {
    try {
      await revealOutputFolder();
      set({ uiBannerError: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not open folder";
      set({ uiBannerError: msg });
    }
  },

  clearUiBanner: () => set({ uiBannerError: null }),
  setUiBannerError: (msg) => set({ uiBannerError: msg }),

  setCaptionStyleDraft: async (style) => {
    const tl = get().timeline;
    if (!tl) return;
    await get().applyOperation({
      operation: "set_timeline_settings",
      arguments: {
        properties: { caption_style: style as unknown as Record<string, unknown> },
      },
    });
  },

  setClipStyleOverrideDraft: async (clipId, style) => {
    const p: Record<string, unknown> = { style_override: style };
    await get().applyOperation({
      operation: "set_clip_property",
      arguments: { clip_id: clipId, properties: p },
    });
  },

  renamePlanFile: async (fromStem, toStem) => {
    const norm = normalizePlanStem(toStem);
    const err = validatePlanStem(norm);
    if (err) {
      set({ uiBannerError: err });
      return;
    }
    if (get().renderStatus === "rendering") {
      set({ uiBannerError: "Wait for export to finish before renaming a plan." });
      return;
    }
    try {
      const { name } = await renamePlanApi(fromStem, norm);
      await get().refreshAvailablePlans();
      const next = normalizePlanStem(name);
      if (typeof localStorage !== "undefined") {
        localStorage.setItem(LAST_OPENED_PLAN_KEY, next);
      }
      if (get().currentPlanName === normalizePlanStem(fromStem)) {
        await get().loadPlan(next, { skipDirtyConfirm: true });
      }
      set({ uiBannerError: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Rename failed";
      set({ uiBannerError: msg });
    }
  },

  duplicatePlanFile: async (fromStem, toStem) => {
    const norm = normalizePlanStem(toStem);
    const err = validatePlanStem(norm);
    if (err) {
      set({ uiBannerError: err });
      return;
    }
    if (get().renderStatus === "rendering") {
      set({
        uiBannerError: "Wait for export to finish before duplicating a plan.",
      });
      return;
    }
    try {
      const { name } = await duplicatePlanApi(fromStem, norm);
      await get().refreshAvailablePlans();
      const next = normalizePlanStem(name);
      set({ uiBannerError: null });
      if (
        typeof window !== "undefined" &&
        window.confirm(`Open copy "${next}"?`)
      ) {
        await get().loadPlan(next, { skipDirtyConfirm: true });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Duplicate failed";
      set({ uiBannerError: msg });
    }
  },

  deletePlanFile: async (stem) => {
    const s = normalizePlanStem(stem);
    if (get().renderStatus === "rendering") {
      set({
        uiBannerError: "Wait for export to finish before deleting a plan.",
      });
      return;
    }
    if (
      typeof window !== "undefined" &&
      !window.confirm(`Delete plan "${s}.json"? This cannot be undone.`)
    ) {
      return;
    }
    try {
      await deletePlanApi(s);
      const list = (await fetchPlanList()).filter((x) => x !== s);
      set({ availablePlans: list, plansListError: null });
      if (get().currentPlanName === s) {
        if (list[0]) {
          await get().loadPlan(list[0], { skipDirtyConfirm: true });
        } else {
          set({
            timeline: null,
            currentPlanName: "",
            timelineLoading: false,
            isDirty: false,
          });
        }
      }
      set({ uiBannerError: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Delete failed";
      set({ uiBannerError: msg });
    }
  },

  setPlayheadSeconds: (t) => set({ playheadSeconds: Math.max(0, t) }),
  setPxPerSecond: (pps) =>
    set({
      pxPerSecond: Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, pps)),
    }),
  setTimelinePlaying: (playing) =>
    set({
      timelinePlaying: playing,
      ...(playing ? { previewPanelMode: "timeline" as PreviewPanelMode } : {}),
    }),
  toggleTimelinePlaying: () =>
    set((s) => {
      const next = !s.timelinePlaying;
      return {
        timelinePlaying: next,
        ...(next ? { previewPanelMode: "timeline" as PreviewPanelMode } : {}),
      };
    }),
  setSelectedClipId: (id) =>
    set({
      selectedClipId: id,
      selectedClipIds: id ? [id] : [],
    }),
  setSelectedClipIds: (ids) =>
    set({
      selectedClipIds: ids,
      selectedClipId: ids.length ? ids[ids.length - 1]! : null,
    }),
  setDragInProgress: (v) => set({ dragInProgress: v }),
  clearOpError: () => set({ opErrorMessage: null }),
  setShortcutToast: (msg) => set({ shortcutToast: msg }),

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
    set({ selectedClipId: null, selectedClipIds: [] });
    return undo;
  },

  separateAudio: async () => {
    const id = get().selectedClipId;
    if (!id) return;
    return get().applyOperation({
      operation: "separate_audio",
      arguments: { clip_id: id },
    });
  },

  reattachAudio: async () => {
    const id = get().selectedClipId;
    if (!id) return;
    return get().applyOperation({
      operation: "reattach_audio",
      arguments: { clip_id: id },
    });
  },

  unlinkClipsAction: async () => {
    const id = get().selectedClipId;
    if (!id) return;
    return get().applyOperation({
      operation: "unlink_clips",
      arguments: { clip_id: id },
    });
  },

  toggleClipLinking: async () => {
    const tl = get().timeline;
    if (!tl?.settings) return;
    const cur = tl.settings.clip_linking_enabled;
    const next = !(cur ?? true);
    return get().applyOperation({
      operation: "set_timeline_settings",
      arguments: { properties: { clip_linking_enabled: next } },
    });
  },

  toggleSelectedTrackMute: async () => {
    const id = get().selectedClipId;
    const tl = get().timeline;
    if (!id || !tl) return;
    for (const tr of tl.tracks ?? []) {
      if (tr.type !== "video" && tr.type !== "audio") continue;
      const hit = (tr.clips ?? []).some((c) => c.id === id);
      if (!hit) continue;
      const next = !(tr.muted ?? false);
      return get().applyOperation({
        operation: "set_track_property",
        arguments: { track_id: tr.id, properties: { muted: next } },
      });
    }
  },

  splitClipsAtTime: async (clipIds, atTimelineTime) => {
    if (clipIds.length === 0) throw new Error("No clips");
    if (clipIds.length === 1) {
      return get().applyOperation({
        operation: "split_clip",
        arguments: {
          clip_id: clipIds[0]!,
          at_timeline_time: atTimelineTime,
        },
      });
    }
    return get().applyOperation({
      operation: "batch_operations",
      arguments: {
        steps: clipIds.map((cid) => ({
          operation: "split_clip",
          arguments: { clip_id: cid, at_timeline_time: atTimelineTime },
        })),
      },
    });
  },

  deleteClipsByIds: async (clipIds) => {
    if (clipIds.length === 0) throw new Error("No clips");
    if (clipIds.length === 1) {
      const undo = await get().applyOperation({
        operation: "delete_clip",
        arguments: { clip_id: clipIds[0]! },
      });
      set({ selectedClipId: null, selectedClipIds: [] });
      return undo;
    }
    const undo = await get().applyOperation({
      operation: "batch_operations",
      arguments: {
        steps: clipIds.map((cid) => ({
          operation: "delete_clip",
          arguments: { clip_id: cid },
        })),
      },
    });
    set({ selectedClipId: null, selectedClipIds: [] });
    return undo;
  },

  separateAudioForClip: async (clipId) => {
    if (!clipId) return;
    return get().applyOperation({
      operation: "separate_audio",
      arguments: { clip_id: clipId },
    });
  },

  reattachAudioForClip: async (clipId) => {
    if (!clipId) return;
    return get().applyOperation({
      operation: "reattach_audio",
      arguments: { clip_id: clipId },
    });
  },

  unlinkClipsForClip: async (clipId) => {
    if (!clipId) return;
    return get().applyOperation({
      operation: "unlink_clips",
      arguments: { clip_id: clipId },
    });
  },

  toggleTrackMuteById: async (trackId) => {
    const tl = get().timeline;
    if (!tl) return;
    const tr = tl.tracks?.find((x) => x.id === trackId);
    if (!tr || (tr.type !== "video" && tr.type !== "audio")) return;
    const next = !(tr.muted ?? false);
    return get().applyOperation({
      operation: "set_track_property",
      arguments: { track_id: trackId, properties: { muted: next } },
    });
  },

  toggleTrackLockById: async (trackId) => {
    const tl = get().timeline;
    if (!tl) return;
    const tr = tl.tracks?.find((x) => x.id === trackId);
    if (!tr || (tr.type !== "video" && tr.type !== "audio")) return;
    const next = !(tr.locked ?? false);
    return get().applyOperation({
      operation: "set_track_property",
      arguments: { track_id: trackId, properties: { locked: next } },
    });
  },

  muteClipToggleById: async (clipId) => {
    const tl = get().timeline;
    if (!tl || !clipId) return;
    const hit = tl.tracks
      ?.flatMap((tr) => (tr.clips ?? []).map((c) => ({ tr, c })))
      .find((x) => x.c.id === clipId);
    if (!hit) return;
    const vol = hit.c.volume !== undefined ? hit.c.volume : 1;
    return get().applyOperation({
      operation: "set_clip_property",
      arguments: {
        clip_id: clipId,
        properties: { volume: vol <= 0 ? 1 : 0 },
      },
    });
  },

  trimTimelineEdge: async (clipId, edge, atTimelineTime) => {
    return get().applyOperation({
      operation: "trim_timeline_edge",
      arguments: {
        clip_id: clipId,
        edge,
        at_timeline_time: atTimelineTime,
      },
    });
  },

  runPlannerJob: async (brief, saveAsStem) => {
    set({ plannerError: null });
    if (typeof window !== "undefined") {
      if (get().isDirty) {
        if (
          !window.confirm(
            "You have unsaved edits. The planner will save a new file and load it; unsaved work will be lost. Continue?",
          )
        ) {
          return;
        }
      }
    }
    const trimmed = brief.trim();
    if (!trimmed) {
      set({ plannerError: "Brief is required." });
      return;
    }
    const stem = normalizePlanStem(saveAsStem);
    if (!stem) {
      set({ plannerError: "Save-as name is required." });
      return;
    }
    const stemErr = validatePlanStem(stem);
    if (stemErr) {
      set({ plannerError: stemErr });
      return;
    }
    if (
      typeof window !== "undefined" &&
      get().availablePlans.includes(stem)
    ) {
      if (
        !window.confirm(
          `This will overwrite plans/${stem}.json on disk. Continue?`,
        )
      ) {
        return;
      }
    }
    set({ plannerRunning: true, plannerError: null });
    try {
      const result = await callPlanner({
        brief: trimmed,
        save_as: stem,
      });
      await get().refreshAvailablePlans();
      const stemFromFile = normalizePlanStem(result.plan_name);
      await get().loadPlan(stemFromFile, { skipDirtyConfirm: true });
      set({ plannerRunning: false, plannerError: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Planner failed";
      set({ plannerRunning: false, plannerError: msg });
    }
  },
}));
