import { apiRequest } from "../lib/apiRequest";

export type PublicSettings = {
  planner_api_key_configured: boolean;
  paths: { footage: string; plans: string; output: string };
  render_defaults: { captions: boolean; max_length: number | null };
};

export async function fetchSettings(): Promise<PublicSettings> {
  const res = await apiRequest("/api/settings");
  return (await res.json()) as PublicSettings;
}

/** Merge paths + render_defaults (+ optional planner key via merge_settings). */
export async function putSettings(body: {
  planner_api_key?: string | null;
  paths?: { footage?: string; plans?: string; output?: string };
  render_defaults?: { captions?: boolean; max_length?: number | null };
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
