import type { TimelineV2 } from "../timeline/types";
import { parseFastApiErrorBody } from "./httpError";

export type SpeechBoundary = {
  clip_id: string;
  track_id: string;
  edge: "in" | "out";
  timeline_time: number;
  source_time?: number | null;
  word?: string | null;
  metrics: Record<string, number | null | undefined>;
  problems: string[];
};

export type SpeechCutAudit = {
  boundaries: SpeechBoundary[];
  problem_count: number;
  summary: string;
};

export type ExportCutQuality = SpeechCutAudit & {
  error?: string;
};

export async function fetchSpeechCutAudit(
  timeline: TimelineV2,
): Promise<SpeechCutAudit> {
  const res = await fetch("/api/timeline/speech-cut-audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeline }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `speech-cut-audit failed (${res.status})`,
    );
  }
  return (await res.json()) as SpeechCutAudit;
}
