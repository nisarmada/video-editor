import { parseFastApiErrorBody } from "./httpError";

export type StyleListItem = {
  id: string;
  name: string;
  path: string;
};

export type StyleListResponse = {
  styles: StyleListItem[];
};

export async function listStyles(): Promise<StyleListResponse> {
  const res = await fetch("/api/styles");
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `List styles failed (${res.status})`,
    );
  }
  return (await res.json()) as StyleListResponse;
}

export type AnalyzeStyleResponse = {
  style_id: string;
  style_name: string;
  file: string;
  profile_path: string;
  profile: Record<string, unknown>;
};

/**
 * Multipart upload: reference video analyzed into plans/styles/<id>.json
 */
export async function analyzeStyle(
  file: File,
  opts?: { style_name?: string; style_id?: string },
): Promise<AnalyzeStyleResponse> {
  const body = new FormData();
  body.append("file", file);
  if (opts?.style_name) body.append("style_name", opts.style_name);
  if (opts?.style_id) body.append("style_id", opts.style_id);

  const res = await fetch("/api/styles/analyze", {
    method: "POST",
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Analyze style failed (${res.status})`,
    );
  }
  return (await res.json()) as AnalyzeStyleResponse;
}
