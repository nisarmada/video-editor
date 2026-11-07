export type FootageProcessStatus = "ready" | "processing" | "pending" | "failed";

import { parseFastApiErrorBody } from "./httpError";

export type FootageKind = "video" | "audio";

export type FootageClip = {
  name: string;
  source: string;
  /** From API: video vs standalone audio (legacy responses omit → treat as video). */
  kind?: FootageKind;
  has_video?: boolean;
  has_audio?: boolean | null;
  duration_seconds: number | null;
  has_proxy: boolean;
  has_thumbnail: boolean;
  process_status?: FootageProcessStatus;
  process_error?: string | null;
  /** none = no audio in file; pending | processing | ready | failed */
  waveform_status?: string;
  waveform_error?: string | null;
  proxy_url: string;
  thumbnail_url: string;
};

type FootageListResponse = {
  clips: FootageClip[];
};

export async function fetchFootageList(): Promise<FootageClip[]> {
  const res = await fetch("/api/footage");
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Failed to load footage (${res.status})`,
    );
  }
  const data = (await res.json()) as FootageListResponse;
  return data.clips ?? [];
}

export async function requestFootageRetranscribe(
  name: string,
): Promise<{ queued: string; removed_index_files: string[] }> {
  const res = await fetch(
    `/api/footage/${encodeURIComponent(name)}/retranscribe`,
    { method: "POST" },
  );
  const t = await res.text();
  if (!res.ok) {
    throw new Error(
      parseFastApiErrorBody(t) || `Re-transcribe failed (${res.status})`,
    );
  }
  return JSON.parse(t) as { queued: string; removed_index_files: string[] };
}

export async function rescanFootageFolder(): Promise<{ queued: string[] }> {
  const res = await fetch("/api/footage/rescan", { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Rescan failed (${res.status})`,
    );
  }
  return (await res.json()) as { queued: string[] };
}

export async function deleteFootageFile(name: string): Promise<void> {
  const res = await fetch(
    `/api/footage/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
  if (res.status === 409) {
    const body = (await res.json()) as { detail?: unknown };
    let plans: string[] = [];
    const d = body.detail;
    if (d && typeof d === "object" && d !== null && "plans" in d) {
      const p = (d as { plans?: unknown }).plans;
      if (Array.isArray(p)) plans = p.filter((x) => typeof x === "string") as string[];
    }
    throw new FootageInUseError(
      `Referenced by plan(s): ${plans.join(", ") || "unknown"}.`,
      plans,
    );
  }
  if (!res.ok) {
    const t = await res.text();
    throw new Error(
      parseFastApiErrorBody(t) || `Delete failed (${res.status})`,
    );
  }
}

/** 409: file still referenced by saved plans */
export class FootageInUseError extends Error {
  plans: string[];

  constructor(message: string, plans: string[]) {
    super(message);
    this.name = "FootageInUseError";
    this.plans = plans;
  }
}

export type UploadProgress = {
  loaded: number;
  total: number;
};

export function uploadFootageFile(
  file: File,
  onProgress?: (p: UploadProgress) => void,
): Promise<{ clip: FootageClip; saved_as: string }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/footage/upload");
    xhr.responseType = "json";

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress({ loaded: e.loaded, total: e.total });
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as { clip: FootageClip; saved_as: string });
        return;
      }
      let detail = xhr.statusText;
      try {
        const j = xhr.response as { detail?: string };
        if (typeof j?.detail === "string") detail = j.detail;
      } catch {
        /* ignore */
      }
      reject(new Error(detail || `Upload failed (${xhr.status})`));
    };

    xhr.onerror = () => reject(new Error("Upload failed (network)"));
    xhr.send(form);
  });
}
