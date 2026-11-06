import type { CaptionStyle, TimelineV2 } from "../timeline/types";

export type CaptionsAssRequest = {
  timeline: TimelineV2;
  style?: CaptionStyle | Record<string, unknown> | null;
  clip_ids?: string[] | null;
  preview_preset?: Record<string, unknown> | null;
  style_target?: "plan" | "clip" | null;
  style_clip_id?: string | null;
};

export type CaptionsAssResponse = {
  ass: string;
  word_count: number;
};

export async function postCaptionsAss(
  body: CaptionsAssRequest,
): Promise<CaptionsAssResponse> {
  const res = await fetch("/api/captions/ass", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || `POST /api/captions/ass failed (${res.status})`);
  }
  return res.json() as Promise<CaptionsAssResponse>;
}

export type CaptionStylesListResponse = {
  built_in: Array<Record<string, unknown>>;
  user: Array<Record<string, unknown>>;
};

export async function fetchCaptionStylesList(): Promise<CaptionStylesListResponse> {
  const res = await fetch("/api/caption-styles");
  if (!res.ok) {
    throw new Error(`GET /api/caption-styles failed (${res.status})`);
  }
  return res.json() as Promise<CaptionStylesListResponse>;
}

export async function putUserCaptionStyle(
  styleId: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const res = await fetch(
    `/api/caption-styles/user/${encodeURIComponent(styleId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || `PUT user caption style failed (${res.status})`);
  }
  return res.json() as Promise<Record<string, unknown>>;
}

export async function deleteUserCaptionStyle(styleId: string): Promise<void> {
  const res = await fetch(
    `/api/caption-styles/user/${encodeURIComponent(styleId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(`DELETE user caption style failed (${res.status})`);
  }
}

export type SystemStatusResponse = {
  ffmpeg_libass: boolean;
  ffmpeg_subtitles_filter: boolean;
};

export async function fetchSystemStatus(): Promise<SystemStatusResponse> {
  const res = await fetch("/api/system/status");
  if (!res.ok) {
    throw new Error(`GET /api/system/status failed (${res.status})`);
  }
  return res.json() as Promise<SystemStatusResponse>;
}

export type FontsListResponse = {
  fonts: string[];
  fontsdir: string;
};

export async function fetchFontsList(): Promise<FontsListResponse> {
  const res = await fetch("/api/fonts");
  if (!res.ok) {
    throw new Error(`GET /api/fonts failed (${res.status})`);
  }
  return res.json() as Promise<FontsListResponse>;
}
