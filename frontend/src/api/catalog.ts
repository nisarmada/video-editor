import { parseFastApiErrorBody } from "./httpError";

export type MediaCatalogEntry = {
  id: string;
  analysis?: { merged_index?: string };
  [key: string]: unknown;
};

export async function fetchMediaCatalog(opts?: {
  names?: string[];
}): Promise<{ entries: MediaCatalogEntry[]; warnings: string[] }> {
  const q =
    opts?.names?.length && opts.names.length > 0
      ? `?names=${opts.names.map(encodeURIComponent).join(",")}`
      : "";
  const res = await fetch(`/api/media/catalog${q}`);
  const t = await res.text();
  if (!res.ok) {
    throw new Error(
      parseFastApiErrorBody(t) || `Catalog failed (${res.status})`,
    );
  }
  return JSON.parse(t) as { entries: MediaCatalogEntry[]; warnings: string[] };
}
