import { parseFastApiErrorBody } from "./httpError";

export type StorageStats = {
  perception_images_bytes: number;
  keyframes_images_bytes: number;
  embedding_json_bytes: number;
  paid_caption_json_bytes?: number;
  total_regenerable_bytes: number;
};

export async function fetchStorageStats(): Promise<StorageStats> {
  const res = await fetch("/api/storage/stats");
  const t = await res.text();
  if (!res.ok) {
    throw new Error(parseFastApiErrorBody(t) || `Storage stats failed (${res.status})`);
  }
  return JSON.parse(t) as StorageStats;
}

export async function clearPaidCaptionCaches(): Promise<{
  removed_files: number;
  freed_bytes: number;
  stats: StorageStats;
}> {
  const res = await fetch("/api/storage/clear-paid-captions", { method: "POST" });
  const t = await res.text();
  if (!res.ok) {
    throw new Error(
      parseFastApiErrorBody(t) || `Clear paid captions failed (${res.status})`,
    );
  }
  return JSON.parse(t) as {
    removed_files: number;
    freed_bytes: number;
    stats: StorageStats;
  };
}

export async function clearRegenerableCaches(): Promise<{
  removed_files: number;
  freed_bytes: number;
  stats: StorageStats;
}> {
  const res = await fetch("/api/storage/clear-regenerable", { method: "POST" });
  const t = await res.text();
  if (!res.ok) {
    throw new Error(parseFastApiErrorBody(t) || `Clear caches failed (${res.status})`);
  }
  return JSON.parse(t) as {
    removed_files: number;
    freed_bytes: number;
    stats: StorageStats;
  };
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
