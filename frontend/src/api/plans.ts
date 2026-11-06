import type { TimelineV2 } from "../timeline/types";
import { parseFastApiErrorBody } from "./httpError";

/** GET /api/plans — returns sorted `*.json` basenames; we expose stems (no suffix). */
export async function fetchPlanList(): Promise<string[]> {
  const res = await fetch("/api/plans");
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Failed to list plans (${res.status})`,
    );
  }
  const data = (await res.json()) as { plans?: string[] };
  const raw = data.plans ?? [];
  return raw.map((p) => p.replace(/\.json$/i, ""));
}

export async function fetchPlan(planName: string): Promise<TimelineV2> {
  const stem = planName.replace(/\.json$/i, "");
  const res = await fetch(`/api/plans/${encodeURIComponent(stem)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Failed to load plan (${res.status})`,
    );
  }
  return (await res.json()) as TimelineV2;
}

/**
 * PUT /api/plans/{name} — body `{ timeline }` (see backend SaveTimelineRequest).
 * 400: detail string or `{ errors: string[] }`.
 */
export async function savePlan(
  planName: string,
  timeline: TimelineV2,
): Promise<{ saved: string }> {
  const stem = planName.replace(/\.json$/i, "");
  const res = await fetch(`/api/plans/${encodeURIComponent(stem)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeline }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Failed to save plan (${res.status})`,
    );
  }
  return (await res.json()) as { saved: string };
}
