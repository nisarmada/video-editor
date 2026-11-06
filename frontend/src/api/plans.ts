import type { TimelineV2 } from "../timeline/types";

export async function fetchPlan(planName: string): Promise<TimelineV2> {
  const stem = planName.replace(/\.json$/i, "");
  const res = await fetch(`/api/plans/${encodeURIComponent(stem)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      text || `Failed to load plan (${res.status})`,
    );
  }
  return (await res.json()) as TimelineV2;
}
