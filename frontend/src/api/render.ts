import { parseFastApiErrorBody } from "./httpError";

/** POST /api/render body — either plan_name or timeline on server. */
export type RenderPlanRequest = {
  plan_name: string;
  output: string;
  captions?: boolean;
  max_length?: number | null;
  video_crf?: number;
};

export type RenderJobPublic = {
  id: string;
  state: string;
  percent: number | null;
  error: string | null;
  log: string;
  output: string | null;
  url: string | null;
};

async function readError(res: Response): Promise<never> {
  const text = await res.text();
  throw new Error(
    parseFastApiErrorBody(text) || `Request failed (${res.status})`,
  );
}

/** Starts background render; poll with {@link getRenderJob}. */
export async function startRender(
  body: RenderPlanRequest,
): Promise<{ job_id: string }> {
  const res = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_name: body.plan_name.replace(/\.json$/i, ""),
      output: body.output,
      captions: body.captions ?? false,
      max_length: body.max_length ?? undefined,
      video_crf: body.video_crf ?? undefined,
    }),
  });
  if (!res.ok) return readError(res);
  return (await res.json()) as { job_id: string };
}

export async function getRenderJob(jobId: string): Promise<RenderJobPublic> {
  const res = await fetch(`/api/render/${encodeURIComponent(jobId)}`);
  if (!res.ok) return readError(res);
  return (await res.json()) as RenderJobPublic;
}

export async function cancelRenderJob(jobId: string): Promise<void> {
  const res = await fetch(
    `/api/render/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
  if (!res.ok) return readError(res);
}
