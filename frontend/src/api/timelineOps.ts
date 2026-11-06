import type { TimelineV2 } from "../timeline/types";

/** Response from POST /api/timeline/apply-op */
export type ApplyOpResult = {
  timeline: TimelineV2;
  undo: Record<string, unknown>;
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
    throw new Error(detail || `apply-op failed (${res.status})`);
  }
  return (await res.json()) as ApplyOpResult;
}
