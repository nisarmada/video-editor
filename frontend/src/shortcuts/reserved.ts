import type { BindingChord } from "./types";
import { chordKey } from "./normalize";

/**
 * Browser/OS-reserved combos we refuse to bind (non-exhaustive safety list).
 */
const RESERVED_SET = new Set<string>([
  "mod+KeyW",
  "mod+KeyT",
  "mod+KeyN",
  "mod+KeyQ",
  "mod+KeyR", // refresh
  "F5",
  "mod+Tab",
  "mod+Shift+KeyT",
  "mod+Shift+KeyN",
]);

export function reservedReason(chord: BindingChord): string | null {
  const k = chordKey(chord);
  if (RESERVED_SET.has(k)) {
    return "This shortcut is reserved by the browser or OS (e.g. close tab, new tab).";
  }
  /* Mod+F4 / Alt+F4 are harder to detect uniformly; skip */
  return null;
}
