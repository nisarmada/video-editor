import type { BindingChord } from "./types";

const isMac =
  typeof navigator !== "undefined" &&
  /Mac|iPhone|iPod|iPad/i.test(navigator.platform ?? navigator.userAgent);

function codeToSymbol(code: string): string {
  if (code.startsWith("Key") && code.length === 4) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  const m: Record<string, string> = {
    Minus: "-",
    Equal: "=",
    BracketLeft: "[",
    BracketRight: "]",
    Backspace: "⌫",
    Delete: "Del",
    Space: "Space",
    ArrowLeft: "←",
    ArrowRight: "→",
    Home: "Home",
    End: "End",
    Escape: "Esc",
    Slash: "/",
  };
  return m[code] ?? code;
}

/** Optional keyLabel from event.key for layout-aware display when capturing */
export function formatChordForDisplay(chord: BindingChord, keyLabel?: string): string {
  const key = keyLabel ?? codeToSymbol(chord.code);

  if (isMac) {
    let s = "";
    if (chord.mod) s += "⌘";
    if (chord.alt) s += "⌥";
    if (chord.shift) s += "⇧";
    s += key;
    return s;
  }

  const parts: string[] = [];
  if (chord.mod) parts.push("Ctrl");
  if (chord.alt) parts.push("Alt");
  if (chord.shift) parts.push("Shift");
  parts.push(key);
  return parts.join("+");
}

/** Plain letter/digit without modifiers — may conflict when typing in fields */
export function isBarePrintableChord(chord: BindingChord): boolean {
  if (chord.mod || chord.alt) return false;
  if (chord.code.startsWith("Key")) return true;
  if (chord.code.startsWith("Digit")) return true;
  return false;
}
