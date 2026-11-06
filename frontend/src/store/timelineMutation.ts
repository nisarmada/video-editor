import type { TimelineInverseOp } from "./timelineStore";

/**
 * Request a timeline mutation: returns false if blocked (drag / apply in flight).
 * Use before calling applyOperation/undo/redo from UI handlers.
 */
export function canMutateTimeline(state: {
  applyOperationInProgress: boolean;
  dragInProgress: boolean;
}): boolean {
  return !state.applyOperationInProgress && !state.dragInProgress;
}

export function parseApplyOpErrorMessage(detail: string): string {
  if (!detail) return "Request failed";
  try {
    const j = JSON.parse(detail) as { detail?: unknown };
    const d = j.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.join("; ");
    if (d && typeof d === "object") return JSON.stringify(d);
  } catch {
    // plain text
  }
  return detail.length > 160 ? `${detail.slice(0, 160)}…` : detail;
}

/** Normalize inverse payload for the apply_undo wrapper (must include `op`). */
export function wrapUndoPayload(inv: TimelineInverseOp): Record<string, unknown> {
  return { undo: inv };
}
