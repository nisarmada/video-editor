import { apiRequest } from "../lib/apiRequest";
import type { KeybindingOverridesMap } from "../shortcuts/types";

export type EditorUiSettingsPayload = {
  shortcutTargeting?: "cursor" | "playhead" | "cursor_else_playhead";
  timelineSnapEnabled?: boolean;
  showCursorTimelineGuide?: boolean;
  cursorActionSelectsClip?: boolean;
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
