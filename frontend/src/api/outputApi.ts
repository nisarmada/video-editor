import { apiRequest } from "../lib/apiRequest";

export type OutputFileRow = {
  name: string;
  size_bytes: number;
  download_url: string;
};

export async function fetchOutputList(): Promise<OutputFileRow[]> {
  const res = await apiRequest("/api/output");
  const data = (await res.json()) as { files?: OutputFileRow[] };
  return data.files ?? [];
}

export async function deleteOutputFile(name: string): Promise<void> {
  await apiRequest(`/api/output/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}
