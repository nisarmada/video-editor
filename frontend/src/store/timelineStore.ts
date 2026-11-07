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
import {
  PlannerAnalysisRequiredError,
  estimatePlanner,
  formatPlannerEstimate,
  formatPlannerUsage,
  readStringList,
  runPlanner as callPlanner,
} from "../api/planner";
import { listStyles, type StyleListItem } from "../api/styles";
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
import {
  LAST_OPENED_PLAN_KEY,
  nextAutoPlanStem,
  normalizePlanStem,
  validatePlanStem,
} from "../utils/planStem";
import {
  canMutateTimeline,
  parseApplyOpErrorMessage,
  wrapUndoPayload,
} from "./timelineMutation";
import type { CaptionStyle, TimelineV2 } from "../timeline/types";
import { findClipById, pruneClipIds } from "../timeline/selection";
import { clipTimelineDuration } from "../timeline/duration";
import { timelinePlaybackQualityWarning } from "../timeline/playbackClock";
import type { GroupMovePlan } from "../timeline/groupMove";

/** Human-readable line after planner succeeds (toast + optional inline). */
function summarizePlannerTimeline(
  tl: TimelineV2,
  cutWarnings?: string[],
): string {
  let videoClips = 0;
  let audioTracksWithClips = 0;
  for (const tr of tl.tracks ?? []) {
    const n = tr.clips?.length ?? 0;
    if (n === 0) continue;
    if (tr.type === "video") videoClips += n;
    if (tr.type === "audio") audioTracksWithClips += 1;
  }
  const base = `Generated timeline with ${videoClips} video clip${videoClips === 1 ? "" : "s"} and ${audioTracksWithClips} audio track${audioTracksWithClips === 1 ? "" : "s"}.`;
  const quality = timelinePlaybackQualityWarning(tl);
  let out = quality ? `${base} ${quality}` : base;
  if (cutWarnings?.length) {
    out += ` Cut check: ${cutWarnings[0]}`;
    if (cutWarnings.length > 1) out += ` (+${cutWarnings.length - 1} more)`;
  }
  return out;
}

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
      canvas: {
        width: 1080,
        height: 1920,
        fps: 30,
        fit: "contain",
        bar_fill: "black",
        fit_position_x: 0.5,
        fit_position_y: 0.5,
      },
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

/** Media bin list filter (Asset strip). */
export type MediaBinCategory = "all" | "video" | "audio";

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

  /** Primary clip for details / single-target fallbacks (anchor when set). */
  selectedClipId: string | null;
  /** Multi-select order (unique). UI-only — not in plan, undo, or dirty. */
  selectedClipIds: string[];
  /** Last plain-clicked clip; stable primary when toggling with Shift. */
  selectedClipAnchorId: string | null;

  /** Selected item in the media bin (footage filename stem). */
  selectedFootageName: string | null;
  /** Shift-click multi-select for AI planner scope (basenames). */
  selectedFootageNames: string[];
  footageClips: FootageClip[];
  footageLoading: boolean;
  footageError: string | null;
  /** Media vs Audio tab — filters footage list. */
  mediaBinCategory: MediaBinCategory;
  setMediaBinCategory: (c: MediaBinCategory) => void;

  /** Which preview is shown — only one player mounts at a time. */
  previewPanelMode: PreviewPanelMode;
  /** Bumped when UI requests source preview of a time range (e.g. speech take). */
  sourcePlaybackRequest: { id: number; start: number; end: number } | null;
  requestSourcePlayback: (start: number, end: number) => void;

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
  /** Sub-step: gathering context vs waiting on Claude vs applying timeline. */
  plannerPhase: "idle" | "context" | "planning" | "applying" | "saving";
  plannerProgressMessage: string | null;
  /** Shown briefly after success (and in toast). */
  plannerSuccessSummary: string | null;
  /** Files left out of the last estimate or run because analysis is missing. */
  plannerUnanalyzed: string[];

  /** Saved style profiles (plans/styles/*.json) for AI planner imitate. */
  styleProfiles: StyleListItem[];
  styleProfilesLoading: boolean;
  styleProfilesError: string | null;
  refreshStyleProfiles: () => Promise<void>;

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
  /**
   * Run AI planner. Writes plans/{save_as}.json; if that is the active plan, applies via
   * replace_timeline (undoable) and auto-saves. Otherwise loads the new file.
   */
  runPlannerJob: (
    brief: string,
    saveAsStem: string,
    opts?: {
      footageScope?: "all" | "selected";
      clipNames?: string[];
      imitateStyleId?: string | null;
      mode?: "draft" | "full";
    },
  ) => Promise<void>;
  /** Save if dirty, then POST /api/render using plan file on disk. */
  exportPlan: (opts?: {
    captions?: boolean;
    video_crf?: number;
  }) => Promise<void>;
  /** Same as exportPlan (export dialog passes explicit options). */
  exportPlanWithOptions: (opts?: {
    captions?: boolean;
    video_crf?: number;
  }) => Promise<void>;
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
  setSelectedClipIds: (ids: string[], opts?: { anchorId?: string | null }) => void;
  toggleClipInSelection: (clipId: string, additive: boolean) => void;
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

  /** Split selected clip(s) at current playhead — one undo step. */
  splitAtPlayhead: () => Promise<TimelineInverseOp>;

  /** Delete all selected clips — one undo step. */
  deleteSelectedClip: () => Promise<TimelineInverseOp>;
  /** Word-safe narration trim on selected audio clips (one undo). */
  refineSelectedAudioCuts: () => Promise<TimelineInverseOp | void>;
  moveClipsToPlans: (plans: GroupMovePlan[]) => Promise<TimelineInverseOp>;
  setClipPropertyBatch: (
    clipIds: string[],
    properties: Record<string, unknown>,
  ) => Promise<TimelineInverseOp | void>;
  runBatchOperationSteps: (
    steps: TimelineEditOp[],
  ) => Promise<TimelineInverseOp | void>;

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
  /** `additive`: Shift+click — toggle in `selectedFootageNames` for planner scope. */
  selectFootage: (name: string, opts?: { additive?: boolean }) => void;
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
  selectedClipAnchorId: null,
  selectedFootageName: null,
  selectedFootageNames: [],
  footageClips: [],
  footageLoading: false,
  footageError: null,
  mediaBinCategory: "all",
  setMediaBinCategory: (c: MediaBinCategory) => set({ mediaBinCategory: c }),
  previewPanelMode: "timeline",
  sourcePlaybackRequest: null,
  requestSourcePlayback: (start, end) =>
    set((s) => ({
      sourcePlaybackRequest: {
        id: (s.sourcePlaybackRequest?.id ?? 0) + 1,
        start,
        end,
      },
      previewPanelMode: "source",
      timelinePlaying: false,
    })),
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
  plannerPhase: "idle",
  plannerProgressMessage: null,
  plannerSuccessSummary: null,
  plannerUnanalyzed: [],
  styleProfiles: [],
  styleProfilesLoading: false,
  styleProfilesError: null,

  refreshStyleProfiles: async () => {
    set({ styleProfilesLoading: true, styleProfilesError: null });
    try {
      const res = await listStyles();
      set({ styleProfiles: res.styles, styleProfilesLoading: false });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to list styles";
      set({
        styleProfiles: [],
        styleProfilesLoading: false,
        styleProfilesError: message,
      });
    }
  },

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

  selectFootage: (name, opts) => {
    if (opts?.additive) {
      set((s) => {
        const cur = new Set(s.selectedFootageNames);
        if (cur.has(name)) cur.delete(name);
        else cur.add(name);
        const arr = [...cur];
        const primary = arr.length ? arr[arr.length - 1]! : null;
        return {
          selectedFootageName: primary,
          selectedFootageNames: arr,
          previewPanelMode: "source",
          timelinePlaying: false,
        };
      });
      return;
    }
    set({
      selectedFootageName: name,
      selectedFootageNames: [name],
      previewPanelMode: "source",
      timelinePlaying: false,
    });
  },

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
          await get().refreshStyleProfiles();
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
      await get().refreshStyleProfiles();
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
        selectedFootageNames: [],
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

  exportPlan: async (opts) => {
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
          render_defaults: { captions: false, max_length: null, video_crf: 23 },
        };
      }
      const rd = settings.render_defaults;
      const { job_id: jobId } = await startRender({
        plan_name: currentPlanName,
        output: outputStem,
        captions: opts?.captions ?? rd.captions,
        max_length: rd.max_length,
        video_crf: opts?.video_crf ?? rd.video_crf ?? 23,
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

  exportPlanWithOptions: async (opts) => get().exportPlan(opts),

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
      selectedClipAnchorId: id,
    }),
  setSelectedClipIds: (ids, opts) =>
    set((s) => {
      const uniq: string[] = [];
      const seen = new Set<string>();
      for (const id of ids) {
        if (!id || seen.has(id)) continue;
        seen.add(id);
        uniq.push(id);
      }
      const anchor =
        opts?.anchorId !== undefined
          ? opts.anchorId
          : s.selectedClipAnchorId && uniq.includes(s.selectedClipAnchorId)
            ? s.selectedClipAnchorId
            : uniq.length
              ? uniq[uniq.length - 1]!
              : null;
      const primary = anchor ?? (uniq.length ? uniq[uniq.length - 1]! : null);
      return {
        selectedClipIds: uniq,
        selectedClipId: primary,
        selectedClipAnchorId: anchor,
      };
    }),
  toggleClipInSelection: (clipId, additive) => {
    const { timeline, selectedClipIds, selectedClipAnchorId } = get();
    if (!timeline) return;
    if (!additive) {
      get().setSelectedClipIds([clipId], { anchorId: clipId });
      return;
    }
    const cur = new Set(selectedClipIds);
    if (cur.has(clipId)) cur.delete(clipId);
    else cur.add(clipId);
    const next = [...cur];
    const anchor =
      selectedClipAnchorId && next.includes(selectedClipAnchorId)
        ? selectedClipAnchorId
        : next.length
          ? clipId
          : null;
    get().setSelectedClipIds(next, { anchorId: anchor });
  },
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
      if (result.refinement_report?.summary) {
        get().setShortcutToast(result.refinement_report.summary);
        window.setTimeout(() => get().setShortcutToast(null), 8000);
      }
      set((s) => {
        const pruned = pruneClipIds(result.timeline, s.selectedClipIds);
        const anchor =
          s.selectedClipAnchorId && pruned.includes(s.selectedClipAnchorId)
            ? s.selectedClipAnchorId
            : pruned.length
              ? pruned[pruned.length - 1]!
              : null;
        return {
          timeline: result.timeline,
          undoStack: [...s.undoStack, result.undo],
          redoStack: [],
          isDirty: true,
          saveStatus: "idle",
          saveError: null,
          selectedClipIds: pruned,
          selectedClipId: anchor,
          selectedClipAnchorId: anchor,
        };
      });
      return result.undo;
    } catch (e) {
      const msg =
        e instanceof Error ? parseApplyOpErrorMessage(e.message) : "Request failed";
      const missing = /Clip not found:\s*'([^']+)'/i.exec(msg);
      if (missing) {
        const bad = missing[1]!;
        set((s) => {
          const nextIds = s.selectedClipIds.filter((id) => id !== bad);
          const anchor = s.selectedClipAnchorId === bad ? null : s.selectedClipAnchorId;
          const primary =
            anchor && nextIds.includes(anchor)
              ? anchor
              : nextIds.length
                ? nextIds[nextIds.length - 1]!
                : null;
          return {
            selectedClipIds: nextIds,
            selectedClipId: primary,
            selectedClipAnchorId: primary,
          };
        });
      }
      set({ opErrorMessage: msg, shortcutToast: msg });
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
      const pruned = pruneClipIds(result.timeline, s.selectedClipIds);
      const anchor =
        s.selectedClipAnchorId && pruned.includes(s.selectedClipAnchorId)
          ? s.selectedClipAnchorId
          : pruned.length
            ? pruned[pruned.length - 1]!
            : null;
      set({
        timeline: result.timeline,
        undoStack: s.undoStack.slice(0, -1),
        redoStack: [...s.redoStack, result.undo],
        isDirty: true,
        saveStatus: "idle",
        saveError: null,
        selectedClipIds: pruned,
        selectedClipId: anchor,
        selectedClipAnchorId: anchor,
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
      const pruned = pruneClipIds(result.timeline, s.selectedClipIds);
      const anchor =
        s.selectedClipAnchorId && pruned.includes(s.selectedClipAnchorId)
          ? s.selectedClipAnchorId
          : pruned.length
            ? pruned[pruned.length - 1]!
            : null;
      set({
        timeline: result.timeline,
        redoStack: s.redoStack.slice(0, -1),
        undoStack: [...s.undoStack, result.undo],
        isDirty: true,
        saveStatus: "idle",
        saveError: null,
        selectedClipIds: pruned,
        selectedClipId: anchor,
        selectedClipAnchorId: anchor,
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
    const { selectedClipIds, playheadSeconds, timeline } = get();
    const ids = selectedClipIds.length ? selectedClipIds : [];
    if (ids.length === 0) {
      throw new Error("No clip selected");
    }
    const toSplit = ids.filter((cid) => {
      const hit = timeline && findClipById(timeline, cid);
      if (!hit) return false;
      const span = clipTimelineDuration(hit.clip, hit.trackType);
      const t1 = hit.clip.timeline_start + span;
      return playheadSeconds >= hit.clip.timeline_start - 1e-9 && playheadSeconds < t1 - 1e-9;
    });
    if (toSplit.length === 0) {
      throw new Error("Playhead is not inside any selected clip.");
    }
    return get().splitClipsAtTime(toSplit, playheadSeconds);
  },

  deleteSelectedClip: async () => {
    const ids = get().selectedClipIds;
    if (ids.length === 0) {
      throw new Error("No clip selected");
    }
    return get().deleteClipsByIds(ids);
  },

  refineSelectedAudioCuts: async () => {
    const { timeline, selectedClipIds } = get();
    if (!timeline || selectedClipIds.length === 0) {
      throw new Error("Select narration (audio) clips first.");
    }
    const audioIds = new Set<string>();
    for (const tr of timeline.tracks ?? []) {
      if (tr.type !== "audio") continue;
      for (const c of tr.clips ?? []) {
        if (c.id && selectedClipIds.includes(c.id)) audioIds.add(c.id);
      }
    }
    if (audioIds.size === 0) {
      throw new Error("Refine cuts applies to audio-track clips only.");
    }
    return get().applyOperation({
      operation: "refine_audio_cuts",
      arguments: { clip_ids: [...audioIds] },
    });
  },

  moveClipsToPlans: async (plans) => {
    if (plans.length === 0) throw new Error("No moves");
    if (plans.length === 1) {
      const p = plans[0]!;
      return get().applyOperation({
        operation: "move_clip",
        arguments: {
          clip_id: p.clipId,
          timeline_start: p.newStart,
          skip_link_expand: true,
        },
      });
    }
    return get().applyOperation({
      operation: "batch_operations",
      arguments: {
        steps: plans.map((p) => ({
          operation: "move_clip",
          arguments: {
            clip_id: p.clipId,
            timeline_start: p.newStart,
            skip_link_expand: true,
          },
        })),
      },
    });
  },

  setClipPropertyBatch: async (clipIds, properties) => {
    if (clipIds.length === 0) return;
    if (clipIds.length === 1) {
      return get().applyOperation({
        operation: "set_clip_property",
        arguments: { clip_id: clipIds[0]!, properties },
      });
    }
    return get().applyOperation({
      operation: "batch_operations",
      arguments: {
        steps: clipIds.map((cid) => ({
          operation: "set_clip_property",
          arguments: { clip_id: cid, properties },
        })),
      },
    });
  },

  runBatchOperationSteps: async (steps) => {
    if (steps.length === 0) return;
    if (steps.length === 1) return get().applyOperation(steps[0]!);
    return get().applyOperation({
      operation: "batch_operations",
      arguments: { steps },
    });
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
      operation: "split_clips_at_time",
      arguments: {
        clip_ids: clipIds,
        at_timeline_time: atTimelineTime,
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
      set({ selectedClipId: null, selectedClipIds: [], selectedClipAnchorId: null });
      return undo;
    }
    const undo = await get().applyOperation({
      operation: "delete_clips",
      arguments: { clip_ids: clipIds },
    });
    set({ selectedClipId: null, selectedClipIds: [], selectedClipAnchorId: null });
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

  runPlannerJob: async (brief, saveAsStem, opts) => {
    set({
      plannerError: null,
      plannerSuccessSummary: null,
      uiBannerError: null,
    });
    const trimmed = brief.trim();
    if (!trimmed) {
      set({ plannerError: "Describe the edit you want (brief is required)." });
      return;
    }
    const requested = normalizePlanStem(saveAsStem);
    const stem = requested || nextAutoPlanStem(get().availablePlans);
    if (!stem) {
      set({ plannerError: "Save-as name is required." });
      return;
    }
    const stemErr = validatePlanStem(stem);
    if (stemErr) {
      set({ plannerError: stemErr });
      return;
    }
    const scope = opts?.footageScope ?? "all";
    const imitateId = opts?.imitateStyleId?.trim() || undefined;
    let clipFilter: string[] | undefined;
    if (scope === "selected") {
      const names = opts?.clipNames ?? get().selectedFootageNames;
      if (!names.length) {
        set({
          plannerError:
            "Select one or more clips in the media bin (Shift+click), or switch scope to “All clips”.",
        });
        return;
      }
      clipFilter = [...names];
    }
    if (
      typeof window !== "undefined" &&
      get().availablePlans.includes(stem)
    ) {
      const replacingOpenPlan =
        get().isDirty && normalizePlanStem(get().currentPlanName) === stem;
      const extra = replacingOpenPlan
        ? " Unsaved edits in the editor will be replaced."
        : "";
      if (
        !window.confirm(
          `This will overwrite plans/${stem}.json on disk.${extra} Continue?`,
        )
      ) {
        return;
      }
    } else if (get().isDirty) {
      const active = normalizePlanStem(get().currentPlanName);
      if (active && active !== stem) {
        await get().savePlan();
        if (get().saveStatus === "error") {
          set({
            plannerError:
              get().saveError ||
              "Could not save the current plan before generating a new one.",
          });
          return;
        }
      }
    }
    const mode = opts?.mode ?? "draft";
    if (mode !== "draft") {
      set({
        plannerError:
          "Full mode is not available yet. Use Draft. The agent loop is a later step.",
        plannerUnanalyzed: [],
      });
      return;
    }
    set({
      plannerRunning: true,
      plannerError: null,
      plannerPhase: "context",
      plannerProgressMessage: "Estimating tokens…",
      plannerUnanalyzed: [],
    });

    try {
      const estimate = await estimatePlanner({
        brief: trimmed,
        ...(clipFilter ? { clip_filenames: clipFilter } : {}),
        ...(imitateId ? { imitate_style_id: imitateId } : {}),
      });
      const line = formatPlannerEstimate(estimate);
      const skipped = estimate.unanalyzed ?? [];
      const skipNote = skipped.length
        ? ` Skipping ${skipped.length} unanalyzed file(s).`
        : "";
      set({
        plannerUnanalyzed: skipped,
        plannerProgressMessage: `${line}.${skipNote}`.trim(),
      });
      if (estimate.file_count <= 0) {
        const names = skipped.length ? skipped.join(", ") : "none listed";
        set({
          plannerRunning: false,
          plannerPhase: "idle",
          plannerProgressMessage: null,
          plannerError: `No analyzed files to plan with. Analyze now: ${names}`,
        });
        return;
      }
      if (
        estimate.confirm &&
        typeof window !== "undefined" &&
        !window.confirm(`${line}.${skipNote} Continue?`)
      ) {
        set({
          plannerRunning: false,
          plannerPhase: "idle",
          plannerProgressMessage: null,
        });
        return;
      }
      set({
        plannerPhase: "planning",
        plannerProgressMessage: `${line}. Sending to planner…`,
      });
      let result: Awaited<ReturnType<typeof callPlanner>>;
      try {
        result = await callPlanner({
          brief: trimmed,
          save_as: stem,
          mode: "draft",
          ...(clipFilter ? { clip_filenames: clipFilter } : {}),
          ...(imitateId ? { imitate_style_id: imitateId } : {}),
        });
      } catch (firstErr) {
        if (firstErr instanceof PlannerAnalysisRequiredError) {
          const need = firstErr.unanalyzed;
          set({
            plannerUnanalyzed: need,
            plannerRunning: false,
            plannerPhase: "idle",
            plannerProgressMessage: null,
            plannerError: need.length
              ? `No analyzed files to plan with. Analyze now: ${need.join(", ")}`
              : "No analyzed files to plan with.",
          });
          return;
        }
        throw firstErr;
      }
      await get().refreshAvailablePlans();
      const stemFromFile = normalizePlanStem(result.plan_name);
      const merged = ensureCaptionStyle(result.timeline);

      const activeStem = normalizePlanStem(get().currentPlanName);
      if (activeStem && stemFromFile === activeStem && get().timeline) {
        set({ plannerPhase: "applying", plannerProgressMessage: "Applying plan to timeline…" });
        await get().applyOperation({
          operation: "replace_timeline",
          arguments: { timeline_data: merged as unknown as Record<string, unknown> },
        });
        set({ plannerPhase: "saving", plannerProgressMessage: "Saving plan file…" });
        await savePlanToServer(stemFromFile, get().timeline!);
        const doneTl = get().timeline!;
        const sum = summarizePlannerTimeline(doneTl, result.cut_quality_warnings);
        const usageLine = formatPlannerUsage(result.usage);
        const fromRun = readStringList(result.usage?.unanalyzed);
        set({
          plannerRunning: false,
          plannerError: null,
          plannerPhase: "idle",
          plannerProgressMessage: null,
          isDirty: false,
          saveStatus: "saved",
          saveError: null,
          plannerSuccessSummary: usageLine ? `${sum} ${usageLine}` : sum,
          plannerUnanalyzed: fromRun ?? get().plannerUnanalyzed,
          selectedClipId: null,
          selectedClipIds: [],
        });
        get().setShortcutToast(sum);
        window.setTimeout(() => get().setShortcutToast(null), 6000);
        return;
      }

      await get().loadPlan(stemFromFile, { skipDirtyConfirm: true });
      const tl2 = get().timeline;
      const sum2 = tl2 ? summarizePlannerTimeline(tl2) : "";
      const usageLine2 = formatPlannerUsage(result.usage);
      const fromRun2 = readStringList(result.usage?.unanalyzed);
      set({
        plannerRunning: false,
        plannerError: null,
        plannerPhase: "idle",
        plannerProgressMessage: null,
        plannerUnanalyzed: fromRun2 ?? get().plannerUnanalyzed,
        ...(sum2
          ? {
              plannerSuccessSummary: usageLine2 ? `${sum2} ${usageLine2}` : sum2,
            }
          : {}),
      });
      if (tl2) {
        const line = summarizePlannerTimeline(tl2);
        get().setShortcutToast(line);
        window.setTimeout(() => get().setShortcutToast(null), 6000);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Planner failed";
      set({
        plannerRunning: false,
        plannerError: msg,
        plannerPhase: "idle",
        plannerProgressMessage: null,
        uiBannerError: msg,
      });
    }
  },
}));
