/** Analysis fields the catalog marks per file. "n/a …" is not missing. */

export type CatalogAnalysis = {
  merged_index?: string;
  transcript?: string;
  silences?: string;
  shots?: string;
  keyframes?: string;
  ai_frame_captions?: string;
  video_perception?: string;
  audio_perception?: string;
  takes?: string;
  waveform_peaks?: { status?: string };
};

const VIDEO_FIELDS = [
  "merged_index",
  "transcript",
  "silences",
  "audio_perception",
  "takes",
  "shots",
  "video_perception",
  "keyframes",
  "ai_frame_captions",
] as const;

const FREE_VIDEO_FIELDS = [
  "merged_index",
  "transcript",
  "silences",
  "audio_perception",
  "takes",
  "shots",
  "video_perception",
  "keyframes",
] as const;

const AUDIO_FIELDS = [
  "merged_index",
  "transcript",
  "silences",
  "audio_perception",
  "takes",
] as const;

export type AnalysisEntry = {
  id: string;
  kind?: string;
  analysis?: CatalogAnalysis;
};

function fieldsForEntry(
  entry: AnalysisEntry,
  includePaidCaptions: boolean,
): readonly string[] {
  if (entry.kind === "audio") return AUDIO_FIELDS;
  const base = includePaidCaptions ? VIDEO_FIELDS : FREE_VIDEO_FIELDS;
  return base;
}

export function missingAnalysisFields(entry: AnalysisEntry): string[] {
  return missingFieldsForEntry(entry, true);
}

/** Local pipeline only (planner can use merged index without paid frame captions). */
export function missingFreeAnalysisFields(entry: AnalysisEntry): string[] {
  return missingFieldsForEntry(entry, false);
}

function missingFieldsForEntry(
  entry: AnalysisEntry,
  includePaidCaptions: boolean,
): string[] {
  const analysis = entry.analysis ?? {};
  const fields = fieldsForEntry(entry, includePaidCaptions);
  const missing: string[] = [];
  for (const field of fields) {
    const value = analysis[field as keyof CatalogAnalysis];
    if (value !== "complete") missing.push(field);
  }
  const waveform = analysis.waveform_peaks?.status;
  if (waveform !== "complete") missing.push("waveform_peaks");
  return missing;
}

export function filesMissingAnalysis(
  entries: AnalysisEntry[],
): { id: string; missing: string[] }[] {
  const out: { id: string; missing: string[] }[] = [];
  for (const entry of entries) {
    const missing = missingAnalysisFields(entry);
    if (missing.length > 0) out.push({ id: entry.id, missing });
  }
  return out;
}

export function filesMissingFreeAnalysis(
  entries: AnalysisEntry[],
): { id: string; missing: string[] }[] {
  const out: { id: string; missing: string[] }[] = [];
  for (const entry of entries) {
    const missing = missingFreeAnalysisFields(entry);
    if (missing.length > 0) out.push({ id: entry.id, missing });
  }
  return out;
}

export function entryNeedsPaidCaptions(entry: AnalysisEntry): boolean {
  if (entry.kind === "audio") return false;
  return entry.analysis?.ai_frame_captions !== "complete";
}
