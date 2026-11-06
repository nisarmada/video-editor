/** localStorage key for last opened plan stem (no .json). */
export const LAST_OPENED_PLAN_KEY = "video-editor:lastPlanStem";

/** Strip optional .json and trim. */
export function normalizePlanStem(raw: string): string {
  return raw.trim().replace(/\.json$/i, "");
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
