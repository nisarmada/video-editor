import {
  type AnalysisEntry,
  entryNeedsPaidCaptions,
  filesMissingFreeAnalysis,
} from "./missingAnalysis";

export type AnalyzeMissingMode = "all" | "free_only";
export type AnalyzeMissingChoice = AnalyzeMissingMode | "cancel";

export function shouldShowAnalyzeMissingDialog(
  remembered: AnalyzeMissingMode | null | undefined,
  paidCaptionFileCount: number,
  freeMissingFileCount: number,
): boolean {
  if (freeMissingFileCount === 0 && paidCaptionFileCount === 0) return false;
  if (remembered) return false;
  return paidCaptionFileCount > 0;
}

/** null = cancel — do not queue. */
export function includeFrameCaptionsForChoice(
  choice: AnalyzeMissingChoice,
): boolean | null {
  if (choice === "cancel") return null;
  return choice === "all";
}

export function rememberModeForChoice(
  choice: AnalyzeMissingChoice,
): AnalyzeMissingMode | null {
  if (choice === "cancel") return null;
  return choice;
}

export function namesToQueue(
  entries: AnalysisEntry[],
  includeFrameCaptions: boolean,
): string[] {
  const names = new Set(filesMissingFreeAnalysis(entries).map((r) => r.id));
  if (includeFrameCaptions) {
    for (const e of entries) {
      if (entryNeedsPaidCaptions(e)) names.add(e.id);
    }
  }
  return [...names];
}

export type BatchProgress = {
  total: number;
  done: number;
  failed: { name: string; error: string }[];
};

export function computeBatchProgress(
  names: string[],
  clips: {
    name: string;
    process_status?: string;
    process_error?: string | null;
  }[],
): BatchProgress {
  const failed: { name: string; error: string }[] = [];
  let done = 0;
  for (const name of names) {
    const clip = clips.find((c) => c.name === name);
    const st = clip?.process_status ?? "ready";
    if (st === "processing" || st === "pending") continue;
    if (st === "failed") {
      failed.push({
        name,
        error: clip?.process_error?.trim() || "Analysis failed",
      });
    }
    done += 1;
  }
  return { total: names.length, done, failed };
}
