/** localStorage key for last opened plan stem (no .json). */
export const LAST_OPENED_PLAN_KEY = "video-editor:lastPlanStem";

/** Strip optional .json and trim. */
export function normalizePlanStem(raw: string): string {
  return raw.trim().replace(/\.json$/i, "");
}

/**
 * Next unused plans/{stem}.json name. The planner field starts here so a run
 * writes a new file instead of asking to overwrite the open plan.
 */
export function nextAutoPlanStem(existing: readonly string[]): string {
  const used = new Set(existing.map((name) => normalizePlanStem(name)));
  for (let n = 1; n < 10000; n += 1) {
    const stem = `plan-${n}`;
    if (!used.has(stem)) return stem;
  }
  return `plan-${Date.now()}`;
}

/** Reject path-like names; return error message or null if ok. */
export function validatePlanStem(raw: string): string | null {
  const stem = normalizePlanStem(raw);
  if (!stem) {
    return "Plan name is required.";
  }
  if (/[/\\]/.test(stem)) {
    return "Name cannot contain path separators.";
  }
  if (stem.includes("..")) {
    return "Invalid name.";
  }
  if (!/^[a-zA-Z0-9._-]+$/.test(stem)) {
    return "Use only letters, numbers, dots, underscores, and hyphens.";
  }
  return null;
}
