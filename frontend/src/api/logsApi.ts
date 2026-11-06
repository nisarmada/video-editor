import { apiRequest } from "../lib/apiRequest";

export type LogEntry = {
  id: number;
  ts: number;
  level: string;
  source: string;
  message: string;
};

export async function fetchLogs(
  since: number,
  limit: number = 200,
): Promise<{ entries: LogEntry[]; latest_id: number }> {
  const q = new URLSearchParams({
    since: String(since),
    limit: String(limit),
  });
  const res = await apiRequest(`/api/logs?${q}`);
  return (await res.json()) as { entries: LogEntry[]; latest_id: number };
}
