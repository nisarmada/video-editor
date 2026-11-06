import { parseFastApiErrorBody } from "./httpError";

/** POST /api/render body (RenderRequest) — either plan_name or timeline on server. */
export type RenderPlanRequest = {
  plan_name: string;
  output: string;
  captions?: boolean;
  max_length?: number | null;
};

export type RenderPlanResponse = {
  /** Relative path under project root, e.g. `output/foo.mp4` */
  output: string;
  /** URL path to download, e.g. `/api/output/foo.mp4` */
  url: string;
};

/**
 * POST /api/render — runs FFmpeg synchronously until the handler returns.
 * On failure: 400/404/500 with FastAPI `detail` (string or list).
 */
export async function renderPlan(body: RenderPlanRequest): Promise<RenderPlanResponse> {
  const res = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_name: body.plan_name.replace(/\.json$/i, ""),
      output: body.output,
      captions: body.captions ?? false,
      max_length: body.max_length ?? undefined,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseFastApiErrorBody(text) || `Render failed (${res.status})`);
  }
  return (await res.json()) as RenderPlanResponse;
}
