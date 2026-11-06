import { apiRequest } from "../lib/apiRequest";

/** Opens the output folder on the host (localhost-only on server). */
export async function revealOutputFolder(): Promise<void> {
  await apiRequest("/api/desktop/reveal-output", { method: "POST" });
}
