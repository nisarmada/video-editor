import { getActionDefinition } from "./actions";
import type { KeybindingOverridesMap, TargetMode } from "./types";
import { getEffectiveBindings } from "./merge";
import { formatChordForDisplay } from "./display";
import { useEditorSettingsStore } from "../store/editorSettingsStore";

function targetHint(
  _actionId: string,
  effective: TargetMode,
  policy: "cursor" | "playhead" | "cursor_else_playhead",
): string {
  const p =
    policy === "cursor"
      ? "cursor"
      : policy === "playhead"
        ? "playhead"
        : "cursor else playhead";
  if (effective === "global") return "";
  return ` · target: ${effective} (${p})`;
}

/** Human-readable chord list for tooltips, e.g. "⌘B, S" — preferred public name */
export function getBindingLabel(
  actionId: string,
  overrides: KeybindingOverridesMap,
): string {
  const keys = formatBindingsList(actionId, overrides);
  const def = getActionDefinition(actionId);
  const ed = useEditorSettingsStore.getState();
  const ov = ed.perActionTargetMode[actionId];
  const effective = ov ?? def?.targetMode ?? "global";
  const hint = def ? targetHint(actionId, effective, ed.shortcutTargeting) : "";
  return keys + hint;
}

/** @deprecated use getBindingLabel */
export function formatBindingsList(
  actionId: string,
  overrides: KeybindingOverridesMap,
): string {
  const chords = getEffectiveBindings(actionId, overrides);
  if (chords.length === 0) return "Unassigned";
  return chords.map((c) => formatChordForDisplay(c)).join(", ");
}

/** "Label (⌘B, S)" for toolbar buttons */
export function getBindingTitle(
  actionId: string,
  overrides: KeybindingOverridesMap,
): string {
  const def = getActionDefinition(actionId);
  const label = def?.label ?? actionId;
  const keys = formatBindingsList(actionId, overrides);
  const ed = useEditorSettingsStore.getState();
  const ov = ed.perActionTargetMode[actionId];
  const effective = ov ?? def?.targetMode ?? "global";
  const hint = def ? targetHint(actionId, effective, ed.shortcutTargeting) : "";
  return `${label} (${keys}${hint})`;
}
