/**
 * Physical key identity (layout-independent). Match using KeyboardEvent.code.
 * Modifiers are explicit — Cmd and Ctrl are both represented as `mod: true` for matching.
 */
export type BindingChord = {
  code: string;
  mod?: boolean;
  shift?: boolean;
  alt?: boolean;
};

/** User overrides: missing key = default; [] = explicitly unbound; [...] = custom list */
export type KeybindingOverridesMap = Record<string, BindingChord[] | [] | undefined>;

export type ShortcutActionCategory =
  | "Editing"
  | "Playback"
  | "Timeline"
  | "Audio"
  | "File"
  | "View";

export type TargetMode = "cursor" | "playhead" | "selection" | "global";

export type ShortcutActionDefinition = {
  id: string;
  label: string;
  category: ShortcutActionCategory;
  description: string;
  /** One action may have several default chords */
  defaultBindings: BindingChord[];
  /** How this action picks time/clips unless overridden in settings */
  targetMode: TargetMode;
};
