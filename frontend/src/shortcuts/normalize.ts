import type { BindingChord } from "./types";

export function chordKey(chord: BindingChord): string {
  const parts: string[] = [];
  if (chord.mod) parts.push("mod");
  if (chord.alt) parts.push("alt");
  if (chord.shift) parts.push("shift");
  parts.push(chord.code);
  return parts.join("+");
}

/** True if this keydown matches the chord (uses code + modifiers; mod = meta OR ctrl). */
export function keydownMatchesChord(e: KeyboardEvent, chord: BindingChord): boolean {
  if (e.code !== chord.code) return false;
  const mod = e.metaKey || e.ctrlKey;
  if (!!chord.mod !== mod) return false;
  if (!!chord.shift !== e.shiftKey) return false;
  if (!!chord.alt !== e.altKey) return false;
  return true;
}

export function parseChordKey(s: string): BindingChord | null {
  const parts = s.split("+").filter(Boolean);
  if (parts.length === 0) return null;
  const code = parts[parts.length - 1]!;
  if (!code.startsWith("Key") && !code.startsWith("Digit") && !/^(F\d+|.*)$/.test(code)) {
    /* still allow BracketLeft, Minus, etc. */
  }
  const c: BindingChord = { code };
  for (let i = 0; i < parts.length - 1; i++) {
    const p = parts[i]!.toLowerCase();
    if (p === "mod") c.mod = true;
    else if (p === "shift") c.shift = true;
    else if (p === "alt") c.alt = true;
  }
  return c;
}

export function cloneChord(c: BindingChord): BindingChord {
  return { ...c };
}
