import { parseFastApiErrorBody } from "./httpError";
import type { TimelineV2 } from "../timeline/types";

export type RunPlannerRequest = {
  brief: string;
  /** Plan filename without path, e.g. draft1 — backend writes plans/{save_as}.json */
  save_as: string;
};

export type RunPlannerResponse = {
  plan_name: string;
  group_id: string;
  usage: Record<string, unknown>;
  timeline: TimelineV2;
};

/**
 * POST /api/planner/run — synchronous; blocks until Claude + validation + write completes.
 */
export async function runPlanner(body: RunPlannerRequest): Promise<RunPlannerResponse> {
  const res = await fetch("/api/planner/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Planner failed (${res.status})`,
    );
  }
  return (await res.json()) as RunPlannerResponse;
}
