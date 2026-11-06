import type { BindingChord, ShortcutActionDefinition, TargetMode } from "./types";

const B = (
  partial: Omit<ShortcutActionDefinition, "defaultBindings" | "targetMode"> & {
    keys: BindingChord[];
    targetMode?: TargetMode;
  },
): ShortcutActionDefinition => {
  const { keys, targetMode, ...rest } = partial;
  return {
    ...rest,
    targetMode: targetMode ?? "global",
    defaultBindings: keys,
  };
};

/**
 * Hardcoded defaults live ONLY here.
 */
export const SHORTCUT_ACTIONS: ShortcutActionDefinition[] = [
  B({
    id: "undo",
    label: "Undo",
    category: "Editing",
    description: "Undo the last timeline edit.",
    keys: [{ code: "KeyZ", mod: true }],
    targetMode: "global",
  }),
  B({
    id: "redo",
    label: "Redo",
    category: "Editing",
    description: "Redo the last undone edit.",
    keys: [{ code: "KeyZ", mod: true, shift: true }],
    targetMode: "global",
  }),
  B({
    id: "split",
    label: "Split clip",
    category: "Editing",
    description: "Split at cursor on timeline, else at playhead on selection.",
    keys: [{ code: "KeyB", mod: true }, { code: "KeyS" }],
    targetMode: "cursor",
  }),
  B({
    id: "delete",
    label: "Delete clip",
    category: "Editing",
    description: "Remove clip under cursor on timeline, else selected clip.",
    keys: [{ code: "Backspace" }, { code: "Delete" }],
    targetMode: "cursor",
  }),
  B({
    id: "copy_clip",
    label: "Copy clip",
    category: "Editing",
    description: "Copy selection; if cursor is on another clip, copy that clip instead.",
    keys: [{ code: "KeyC", mod: true }],
    targetMode: "cursor",
  }),
  B({
    id: "paste_clip",
    label: "Paste clip",
    category: "Editing",
    description: "Paste at cursor time on timeline, else at playhead.",
    keys: [{ code: "KeyV", mod: true }],
    targetMode: "cursor",
  }),
  B({
    id: "select_all_clips",
    label: "Select all clips",
    category: "Editing",
    description: "Select every clip on the timeline.",
    keys: [{ code: "KeyA", mod: true }],
    targetMode: "global",
  }),
  B({
    id: "deselect_clips",
    label: "Deselect clips",
    category: "Editing",
    description: "Clear timeline clip selection.",
    keys: [{ code: "Escape" }],
    targetMode: "global",
  }),

  B({
    id: "play_pause",
    label: "Play / Pause timeline",
    category: "Playback",
    description: "Toggle timeline preview playback (when not typing in a field).",
    keys: [{ code: "Space" }],
    targetMode: "global",
  }),

  B({
    id: "zoom_in",
    label: "Zoom in",
    category: "View",
    description: "Increase timeline zoom; anchor on cursor time when over timeline.",
    keys: [{ code: "Equal" }],
    targetMode: "cursor",
  }),
  B({
    id: "zoom_out",
    label: "Zoom out",
    category: "View",
    description: "Decrease timeline zoom; anchor on cursor time when over timeline.",
    keys: [{ code: "Minus" }],
    targetMode: "cursor",
  }),
  B({
    id: "cheat_sheet",
    label: "Keyboard shortcuts help",
    category: "View",
    description: "Show the shortcut cheat sheet overlay.",
    keys: [{ code: "Slash", shift: true }],
    targetMode: "global",
  }),
  B({
    id: "open_keyboard_settings",
    label: "Open keyboard settings",
    category: "View",
    description: "Open the keyboard shortcuts editor (toolbar only by default).",
    keys: [],
    targetMode: "global",
  }),

  B({
    id: "step_frame_back",
    label: "Step frame backward",
    category: "Timeline",
    description: "Move the playhead back one frame (timeline mode).",
    keys: [{ code: "ArrowLeft" }],
    targetMode: "global",
  }),
  B({
    id: "step_frame_forward",
    label: "Step frame forward",
    category: "Timeline",
    description: "Move the playhead forward one frame (timeline mode).",
    keys: [{ code: "ArrowRight" }],
    targetMode: "global",
  }),
  B({
    id: "jump_start",
    label: "Jump to start",
    category: "Timeline",
    description: "Move the playhead to the beginning.",
    keys: [{ code: "Home" }],
    targetMode: "global",
  }),
  B({
    id: "jump_end",
    label: "Jump to end",
    category: "Timeline",
    description: "Move the playhead to the end of the edit.",
    keys: [{ code: "End" }],
    targetMode: "global",
  }),
  B({
    id: "move_playhead_to_cursor",
    label: "Move playhead to cursor",
    category: "Timeline",
    description: "Set playhead to timeline time under the pointer.",
    keys: [],
    targetMode: "cursor",
  }),
  B({
    id: "trim_start_to_cursor",
    label: "Trim start to cursor",
    category: "Editing",
    description: "Trim clip in point to cursor time (strictly inside clip).",
    keys: [],
    targetMode: "cursor",
  }),
  B({
    id: "trim_end_to_cursor",
    label: "Trim end to cursor",
    category: "Editing",
    description: "Trim clip out point to cursor time (strictly inside clip).",
    keys: [],
    targetMode: "cursor",
  }),
  B({
    id: "toggle_track_lock",
    label: "Lock / unlock track",
    category: "Timeline",
    description: "Toggle lock on the track under the cursor.",
    keys: [],
    targetMode: "cursor",
  }),

  B({
    id: "separate_audio",
    label: "Separate audio",
    category: "Audio",
    description: "Detach audio from the video clip under the cursor (or selection).",
    keys: [{ code: "KeyS", mod: true, shift: true }],
    targetMode: "cursor",
  }),
  B({
    id: "reattach_audio",
    label: "Reattach audio",
    category: "Audio",
    description: "Merge detached audio back with the video clip under cursor.",
    keys: [],
    targetMode: "cursor",
  }),
  B({
    id: "unlink_clips",
    label: "Unlink clips",
    category: "Audio",
    description: "Clear the link between paired clips under cursor.",
    keys: [],
    targetMode: "cursor",
  }),
  B({
    id: "toggle_clip_linking",
    label: "Toggle clip linking",
    category: "Audio",
    description: "Turn CapCut-style clip linking on or off.",
    keys: [{ code: "KeyL" }],
    targetMode: "global",
  }),
  B({
    id: "toggle_track_mute",
    label: "Mute/unmute track",
    category: "Audio",
    description: "Toggle mute on the video or audio track under the cursor.",
    keys: [{ code: "KeyM" }],
    targetMode: "cursor",
  }),
  B({
    id: "mute_clip",
    label: "Mute/unmute clip",
    category: "Audio",
    description: "Toggle clip volume between 0 and 1 on the clip under cursor.",
    keys: [],
    targetMode: "cursor",
  }),

  B({
    id: "save_plan",
    label: "Save plan",
    category: "File",
    description: "Save the current timeline to disk.",
    keys: [{ code: "KeyS", mod: true }],
    targetMode: "global",
  }),
  B({
    id: "export_render",
    label: "Export / render",
    category: "File",
    description: "Save if needed and start export render.",
    keys: [{ code: "KeyE", mod: true }],
    targetMode: "global",
  }),
];

const BY_ID: Record<string, ShortcutActionDefinition> = {};
for (const a of SHORTCUT_ACTIONS) {
  BY_ID[a.id] = a;
}

export function getActionDefinition(id: string): ShortcutActionDefinition | undefined {
  return BY_ID[id];
}

export function isKnownActionId(id: string): boolean {
  return id in BY_ID;
}
