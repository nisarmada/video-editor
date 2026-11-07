import type { TimelineV2 } from "../timeline/types";
import { parseFastApiErrorBody } from "./httpError";

/** Response from POST /api/timeline/apply-op */
export type AudioRefinementReport = {
  summary?: string;
  moves?: {
    clip_id: string;
    delta_in_ms: number;
    delta_out_ms: number;
  }[];
};

export type ApplyOpResult = {
  timeline: TimelineV2;
  /** Inverse op payload from the server (`docs/commands.md`). */
  undo: Record<string, unknown>;
  refinement_report?: AudioRefinementReport;
};

export async function applyTimelineOperation(
  timeline: TimelineV2,
  operation: string,
  argumentsObj: Record<string, unknown> = {},
): Promise<ApplyOpResult> {
  const res = await fetch("/api/timeline/apply-op", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      timeline,
      operation,
      arguments: argumentsObj,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    const msg = parseFastApiErrorBody(detail) || `apply-op failed (${res.status})`;
    const err = new Error(msg);
    (err as Error & { status?: number }).status = res.status;
    throw err;
  }
  return (await res.json()) as ApplyOpResult;
}
