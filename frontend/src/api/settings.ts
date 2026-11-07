import { apiRequest } from "../lib/apiRequest";
import type { KeybindingOverridesMap } from "../shortcuts/types";

export type EditorUiSettingsPayload = {
  shortcutTargeting?: "cursor" | "playhead" | "cursor_else_playhead";
  timelineSnapEnabled?: boolean;
  showCursorTimelineGuide?: boolean;
  cursorActionSelectsClip?: boolean;
  marqueeOverlapMode?: "touch" | "inside";
  selectLinkedClipsTogether?: boolean;
  perActionTargetMode?: Partial<
    Record<string, "cursor" | "playhead" | "selection" | "global">
  >;
};

export type AudioCutRefineSettings = {
  enabled?: boolean;
  pre_roll_ms?: number;
  post_roll_ms?: number;
  snap_window_ms?: number;
  fade_ms?: number;
  join_crossfade_ms?: number;
  energy_disagree_ms?: number;
};

export type PlannerSettings = {
  catalog_token_budget: number;
  confirm_above_usd: number;
  max_input_tokens: number;
  max_cost_usd: number;
  max_iterations: number;
  max_images: number;
  max_wall_time_s: number;
  triage_model: string;
  edit_model: string;
};

export const PLANNER_DEFAULTS: PlannerSettings = {
  catalog_token_budget: 8000,
  confirm_above_usd: 0.1,
  max_input_tokens: 24000,
  max_cost_usd: 1,
  max_iterations: 3,
  max_images: 0,
  max_wall_time_s: 180,
  triage_model: "claude-haiku-4-5-20251001",
  edit_model: "claude-sonnet-5-5",
};

export type TranscriptionSettings = {
  model_size: "small" | "medium";
  keep_quiet_speech: boolean;
};

export const TRANSCRIPTION_DEFAULTS: TranscriptionSettings = {
  model_size: "small",
  keep_quiet_speech: false,
};

export type EmbeddingSettings = {
  method: "hash" | "sentence_transformer";
  model_name: string;
};

export const EMBEDDING_DEFAULTS: EmbeddingSettings = {
  method: "hash",
  model_name: "all-MiniLM-L6-v2",
};

export type PublicSettings = {
  planner_api_key_configured: boolean;
  paths: { footage: string; plans: string; output: string };
  render_defaults: {
    captions: boolean;
    max_length: number | null;
    video_crf?: number;
  };
  /** User shortcut overrides; omitted or {} if unset */
  keybindings?: KeybindingOverridesMap;
  ui?: EditorUiSettingsPayload;
  audio_cut_refine?: AudioCutRefineSettings;
  planner?: PlannerSettings;
  transcription?: TranscriptionSettings;
  embedding?: EmbeddingSettings;
};

export async function fetchSettings(): Promise<PublicSettings> {
  const res = await apiRequest("/api/settings");
  return (await res.json()) as PublicSettings;
}

/** Merge paths + render_defaults + optional keybindings (+ optional planner key). */
export async function putSettings(body: {
  planner_api_key?: string | null;
  paths?: { footage?: string; plans?: string; output?: string };
  render_defaults?: {
    captions?: boolean;
    max_length?: number | null;
    video_crf?: number;
  };
  keybindings?: KeybindingOverridesMap | null;
  ui?: EditorUiSettingsPayload | null;
  audio_cut_refine?: AudioCutRefineSettings | null;
  planner?: Partial<PlannerSettings> | null;
  transcription?: Partial<TranscriptionSettings> | null;
  embedding?: Partial<EmbeddingSettings> | null;
}): Promise<PublicSettings> {
  const res = await apiRequest("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await res.json()) as PublicSettings;
}

export async function putPlannerApiKey(apiKey: string): Promise<void> {
  await apiRequest("/api/settings/planner-api-key", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function testPlannerConnection(): Promise<void> {
  await apiRequest("/api/settings/test-planner", { method: "POST" });
}
