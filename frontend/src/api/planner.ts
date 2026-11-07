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
  /** draft = one compact call. full is refused until a later step. */
  mode?: "draft" | "full";
};

export type PlannerEstimate = {
  file_count: number;
  omitted_count: number;
  unanalyzed: string[];
  input_tokens: number;
  est_cost_usd: number;
  confirm: boolean;
  model: string;
  catalog_build_ms: number;
  mode: string;
};

/** ~9k for thousands of tokens, otherwise the raw estimate. */
export function formatTokenCount(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens < 1000) {
    return `~${Math.max(0, Math.round(tokens || 0))}`;
  }
  const thousands = tokens / 1000;
  const rounded = thousands >= 10 ? Math.round(thousands) : Math.round(thousands * 10) / 10;
  return `~${rounded}k`;
}

/** Planner bar line before a run: "6 files, ~9k input tokens, est. $0.04". */
export function formatPlannerEstimate(est: PlannerEstimate): string {
  const cost = est.est_cost_usd;
  const dollars =
    Number.isFinite(cost) && cost > 0 && cost < 0.01
      ? cost.toFixed(4)
      : (Number.isFinite(cost) ? cost : 0).toFixed(2);
  return `${est.file_count} files, ${formatTokenCount(est.input_tokens)} input tokens, est. $${dollars}`;
}

/** Extra lines for the live estimate strip (budget-omitted count + unanalyzed names). */
export function formatPlannerEstimateNotes(est: PlannerEstimate): string[] {
  const lines: string[] = [];
  if (est.omitted_count > 0) {
    lines.push(
      `${est.omitted_count} analyzed file(s) omitted from the catalog (token budget)`,
    );
  }
  if (est.unanalyzed.length > 0) {
    lines.push(
      `Excluded (no merged index): ${est.unanalyzed.join(", ")}`,
    );
  }
  return lines;
}

export function readStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is string => typeof item === "string");
}

/** After a run: tokens, dollars, stage timings, and today's total. */
export function formatPlannerUsage(usage: Record<string, unknown> | undefined): string {
  if (!usage) return "";
  const input = Number(usage.input_tokens ?? 0);
  const output = Number(usage.output_tokens ?? 0);
  const cost = Number(usage.cost_usd ?? 0);
  const timings = usage.timings_ms as Record<string, number> | undefined;
  const day = usage.day_total as { cost_usd?: number } | undefined;
  const bits = [
    `${Number.isFinite(input) ? input : 0} in / ${Number.isFinite(output) ? output : 0} out tokens`,
    `$${Number.isFinite(cost) ? cost.toFixed(4) : "0.0000"}`,
  ];
  if (timings && typeof timings === "object") {
    bits.push(
      `catalog ${timings.catalog_build ?? 0} ms, model ${timings.model_call ?? 0} ms, validation ${timings.validation ?? 0} ms`,
    );
  }
  if (day && typeof day.cost_usd === "number") {
    bits.push(`today $${day.cost_usd.toFixed(4)}`);
  }
  if (typeof usage.budget_stop === "string" && usage.budget_stop) {
    bits.push(`stopped: ${usage.budget_stop}`);
  }
  return bits.join(" · ");
}

export type RunPlannerResponse = {
  plan_name: string;
  group_id: string;
  usage: Record<string, unknown>;
  timeline: TimelineV2;
  cut_quality_warnings?: string[];
  speech_edit_warnings?: {
    code: string;
    severity: string;
    clip_id?: string | null;
    message: string;
    suggested_source_out?: number;
  }[];
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

/** POST /api/planner/estimate — local catalog math, no model call. */
export async function estimatePlanner(body: {
  brief: string;
  clip_filenames?: string[];
  imitate_style_id?: string | null;
}): Promise<PlannerEstimate> {
  const res = await fetch("/api/planner/estimate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(
      parseFastApiErrorBody(text) || `Estimate failed (${res.status})`,
    );
  }
  return JSON.parse(text) as PlannerEstimate;
}

export { requestFootageAnalyze } from "./footage";

export async function requestSpeechReadback(body: {
  brief: string;
  timeline: TimelineV2;
  mock?: boolean;
  confirm_paid?: boolean;
}): Promise<{
  readback: unknown[];
  script: string;
  verdict: Record<string, unknown>;
}> {
  const res = await fetch("/api/planner/speech-readback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      brief: body.brief,
      timeline: body.timeline,
      mock: body.mock ?? true,
      confirm_paid: body.confirm_paid ?? false,
    }),
  });
  const t = await res.text();
  if (!res.ok) {
    throw new Error(
      parseFastApiErrorBody(t) || `Speech read-back failed (${res.status})`,
    );
  }
  return JSON.parse(t) as {
    readback: unknown[];
    script: string;
    verdict: Record<string, unknown>;
  };
}

