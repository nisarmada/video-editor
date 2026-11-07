import { parseFastApiErrorBody } from "./httpError";
import type { TimelineV2 } from "../timeline/types";

export class PlannerAnalysisRequiredError extends Error {
  readonly unanalyzed: string[];

  constructor(unanalyzed: string[]) {
    super("Merged index missing — analysis required.");
    this.name = "PlannerAnalysisRequiredError";
    this.unanalyzed = unanalyzed;
  }
}

export type RunPlannerRequest = {
  brief: string;
  /** Plan filename without path, e.g. draft1 — backend writes plans/{save_as}.json */
  save_as: string;
  /** Optional: limit planning context to these footage basenames. */
  clip_filenames?: string[];
  /** Optional: plans/styles/<id>.json — mirror these pacing/visual rules in the system prompt. */
  imitate_style_id?: string | null;
  /** Allow planner to run with incomplete merged indexes (not recommended). */
  allow_without_merged_index?: boolean;
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
  const text = await res.text();
  if (!res.ok) {
    if (res.status === 409) {
      try {
        const j = JSON.parse(text) as { detail?: unknown };
        const d = j.detail;
        if (
          d !== null &&
          typeof d === "object" &&
          "unanalyzed" in d &&
          Array.isArray((d as { unanalyzed: unknown }).unanalyzed)
        ) {
          const arr = (d as { unanalyzed: string[] }).unanalyzed.filter(
            (x) => typeof x === "string",
          );
          if (arr.length > 0) {
            throw new PlannerAnalysisRequiredError(arr);
          }
        }
      } catch (e) {
        if (e instanceof PlannerAnalysisRequiredError) throw e;
      }
    }
    throw new Error(
      parseFastApiErrorBody(text) || `Planner failed (${res.status})`,
    );
  }
  return JSON.parse(text) as RunPlannerResponse;
}

/**
 * Queue full analysis pipeline for the given basenames (or every file when all=true).
 */
export async function requestFootageAnalyze(body: {
  names?: string[];
  all?: boolean;
}): Promise<{ queued: string[] }> {
  const res = await fetch("/api/footage/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      body.all ? { all: true } : { names: body.names ?? [] },
    ),
  });
  const t = await res.text();
  if (!res.ok) {
    throw new Error(
      parseFastApiErrorBody(t) || `Analyze failed (${res.status})`,
    );
  }
  return JSON.parse(t) as { queued: string[] };
}

