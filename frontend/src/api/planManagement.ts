import { apiRequest } from "../lib/apiRequest";

export async function renamePlan(
  stem: string,
  toStem: string,
): Promise<{ name: string }> {
  const s = stem.replace(/\.json$/i, "");
  const res = await apiRequest(`/api/plans/${encodeURIComponent(s)}/rename`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to: toStem }),
  });
  return (await res.json()) as { name: string };
}

export async function duplicatePlan(
  stem: string,
  toStem: string,
): Promise<{ name: string }> {
  const s = stem.replace(/\.json$/i, "");
  const res = await apiRequest(`/api/plans/${encodeURIComponent(s)}/duplicate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to: toStem }),
  });
  return (await res.json()) as { name: string };
}

export async function deletePlan(stem: string): Promise<void> {
  const s = stem.replace(/\.json$/i, "");
  await apiRequest(`/api/plans/${encodeURIComponent(s)}`, { method: "DELETE" });
}
