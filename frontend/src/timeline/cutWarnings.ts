import type { SpeechBoundary } from "../api/speechCuts";
import type { TimelineClip } from "./types";

/** Plan-side + audit flags for timeline warning markers. */
export function clipHasCutWarning(
  clip: TimelineClip,
  auditOut?: SpeechBoundary | null,
): boolean {
  if (auditOut?.problems?.length) return true;
  const q = clip.speech_cut_quality as Record<string, unknown> | undefined;
  if (!q) return false;
  const intent =
    typeof clip.cut_intent === "object" && clip.cut_intent && "end" in clip.cut_intent
      ? String((clip.cut_intent as { end?: string }).end ?? "")
      : "";
  const decay = Number(q.decay_retained_ms);
  if (
    (intent === "complete" || intent === "") &&
    Number.isFinite(decay) &&
    decay < 40
  ) {
    return true;
  }
  const click = Number(q.click_score);
  if (Number.isFinite(click) && click > 0.12) return true;
  if (clip.speech_transition_tight) return true;
  const flags = clip.cut_warning_flags;
  if (Array.isArray(flags) && flags.length > 0) return true;
  return false;
}

export function boundaryLabel(problems: string[]): string {
  if (!problems.length) return "OK";
  return problems.join(", ");
}
