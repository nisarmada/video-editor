import { SHORTCUT_ACTIONS, isKnownActionId } from "./actions";
import type { BindingChord, KeybindingOverridesMap } from "./types";
import { chordKey } from "./normalize";

export function getDefaultBindings(actionId: string): BindingChord[] {
  const def = SHORTCUT_ACTIONS.find((a) => a.id === actionId);
  return def ? def.defaultBindings.map((b) => ({ ...b })) : [];
}

/** Effective bindings: undefined override → defaults; [] → unbound */
export function getEffectiveBindings(
  actionId: string,
  overrides: KeybindingOverridesMap,
): BindingChord[] {
  const raw = overrides[actionId];
  if (raw === undefined) return getDefaultBindings(actionId);
  if (Array.isArray(raw) && raw.length === 0) return [];
  return (raw as BindingChord[]).map((b) => ({ ...b }));
}

export type BindingState = "default" | "customized" | "unbound";

export function getBindingState(
  actionId: string,
  overrides: KeybindingOverridesMap,
): BindingState {
  const raw = overrides[actionId];
  if (raw === undefined) return "default";
  if (Array.isArray(raw) && raw.length === 0) return "unbound";
  return "customized";
}

/** All chords used by an action id after merge */
export function buildChordToActionMap(
  overrides: KeybindingOverridesMap,
): Map<string, string> {
  const map = new Map<string, string>();
  /* Later actions in SHORTCUT_ACTIONS win the same chord (matches global handler). */
  for (const a of SHORTCUT_ACTIONS) {
    const chords = getEffectiveBindings(a.id, overrides);
    for (const c of chords) {
      map.set(chordKey(c), a.id);
    }
  }
  return map;
}

export function findActionForChord(
  e: KeyboardEvent,
  overrides: KeybindingOverridesMap,
  match: (ev: KeyboardEvent, chord: BindingChord) => boolean,
): string | null {
  let winner: string | null = null;
  for (const a of SHORTCUT_ACTIONS) {
    const chords = getEffectiveBindings(a.id, overrides);
    for (const c of chords) {
      if (match(e, c)) winner = a.id;
    }
  }
  return winner;
}

export type ImportResult = {
  overrides: KeybindingOverridesMap;
  unknownIds: string[];
};

export function validateImportOverrides(raw: unknown): ImportResult {
  const unknownIds: string[] = [];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { overrides: {}, unknownIds: [] };
  }
  const o = raw as Record<string, unknown>;
  const keys = o.keybindings ?? o;
  if (typeof keys !== "object" || keys === null || Array.isArray(keys)) {
    return { overrides: {}, unknownIds: [] };
  }
  const out: KeybindingOverridesMap = {};
  for (const [id, val] of Object.entries(keys as Record<string, unknown>)) {
    if (!isKnownActionId(id)) {
      unknownIds.push(id);
      continue;
    }
    if (val === null) {
      out[id] = undefined;
      continue;
    }
    if (Array.isArray(val)) {
      const chords: BindingChord[] = [];
      for (const item of val) {
        if (!item || typeof item !== "object") continue;
        const c = item as Record<string, unknown>;
        const code = typeof c.code === "string" ? c.code : "";
        if (!code) continue;
        chords.push({
          code,
          mod: Boolean(c.mod),
          shift: Boolean(c.shift),
          alt: Boolean(c.alt),
        });
      }
      out[id] = chords;
    }
  }
  return { overrides: out, unknownIds };
}
