/**
 * Central labels + shortcut hints for tooltips and the keybinding layer.
 */
export const timelineShortcuts = {
  undo: { label: "Undo", keys: "⌘Z" },
  redo: { label: "Redo", keys: "⌘⇧Z" },
  split: { label: "Split at playhead", keys: "—" },
  delete: { label: "Delete clip", keys: "⌫" },
  copyClip: { label: "Copy clip", keys: "⌘C" },
  pasteClip: { label: "Paste clip", keys: "⌘V" },
  separateAudio: {
    label: "Separate audio",
    keys: "⌘⇧S",
  },
  reattachAudio: { label: "Reattach audio", keys: "—" },
  unlink: { label: "Unlink clips", keys: "—" },
  toggleLinking: { label: "Toggle clip linking", keys: "⌘L" },
  muteTrack: { label: "Mute track", keys: "M" },
  muteClip: { label: "Mute clip", keys: "—" },
} as const;

export function shortcutTitle(
  id: keyof typeof timelineShortcuts,
): string {
  const s = timelineShortcuts[id];
  return `${s.label} (${s.keys})`;
}

export function shortcutKeys(id: keyof typeof timelineShortcuts): string {
  return timelineShortcuts[id].keys;
}
