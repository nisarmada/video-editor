import { create } from "zustand";
import { fetchSettings, putSettings, type PublicSettings } from "../api/settings";
import type { TargetMode } from "../shortcuts/types";

const LS = "video-editor-ui-settings";

export type ShortcutTargetingPolicy = "cursor" | "playhead" | "cursor_else_playhead";

export type MarqueeOverlapMode = "touch" | "inside";

export type EditorUiSettings = {
  shortcutTargeting: ShortcutTargetingPolicy;
  /** When true, snap playhead/cursor time to ~6px grid in timeline coords when shortcuts use timeline time. */
  timelineSnapEnabled: boolean;
  showCursorTimelineGuide: boolean;
  /** When true, clicking a clip under the cursor applies selection before the action. */
  cursorActionSelectsClip: boolean;
  /** Marquee selects clips that touch the box vs must be fully inside. */
  marqueeOverlapMode: MarqueeOverlapMode;
  /** When true, clicking one separated A/V clip also selects its partner. */
  selectLinkedClipsTogether: boolean;
};

const defaults: EditorUiSettings = {
  shortcutTargeting: "cursor",
  timelineSnapEnabled: true,
  showCursorTimelineGuide: true,
  cursorActionSelectsClip: false,
  marqueeOverlapMode: "touch",
  selectLinkedClipsTogether: true,
};

export type PerActionTargetOverrideMap = Partial<Record<string, TargetMode>>;

type State = EditorUiSettings & {
  perActionTargetMode: PerActionTargetOverrideMap;
  hydrated: boolean;
  hydrateFromApi: () => Promise<void>;
  setUi: (patch: Partial<EditorUiSettings>) => void;
  setPerActionTargetMode: (id: string, mode: TargetMode | undefined) => void;
};

function readLocal(): { ui: EditorUiSettings; perActionTargetMode: PerActionTargetOverrideMap } {
  try {
    const raw = localStorage.getItem(LS);
    if (!raw) return { ui: { ...defaults }, perActionTargetMode: {} };
    const j = JSON.parse(raw) as unknown;
    if (!j || typeof j !== "object" || Array.isArray(j)) {
      return { ui: { ...defaults }, perActionTargetMode: {} };
    }
    const o = j as Record<string, unknown>;
    const ui: EditorUiSettings = {
      ...defaults,
      ...(typeof o.shortcutTargeting === "string"
        ? { shortcutTargeting: o.shortcutTargeting as ShortcutTargetingPolicy }
        : {}),
      ...(typeof o.timelineSnapEnabled === "boolean"
        ? { timelineSnapEnabled: o.timelineSnapEnabled }
        : {}),
      ...(typeof o.showCursorTimelineGuide === "boolean"
        ? { showCursorTimelineGuide: o.showCursorTimelineGuide }
        : {}),
      ...(typeof o.cursorActionSelectsClip === "boolean"
        ? { cursorActionSelectsClip: o.cursorActionSelectsClip }
        : {}),
      ...(o.marqueeOverlapMode === "touch" || o.marqueeOverlapMode === "inside"
        ? { marqueeOverlapMode: o.marqueeOverlapMode }
        : {}),
      ...(typeof o.selectLinkedClipsTogether === "boolean"
        ? { selectLinkedClipsTogether: o.selectLinkedClipsTogether }
        : {}),
    };
    const pam =
      o.perActionTargetMode && typeof o.perActionTargetMode === "object" && !Array.isArray(o.perActionTargetMode)
        ? (o.perActionTargetMode as PerActionTargetOverrideMap)
        : {};
    return { ui, perActionTargetMode: pam };
  } catch {
    return { ui: { ...defaults }, perActionTargetMode: {} };
  }
}

function writeLocal(s: State): void {
  try {
    localStorage.setItem(
      LS,
      JSON.stringify({
        shortcutTargeting: s.shortcutTargeting,
        timelineSnapEnabled: s.timelineSnapEnabled,
        showCursorTimelineGuide: s.showCursorTimelineGuide,
        cursorActionSelectsClip: s.cursorActionSelectsClip,
        marqueeOverlapMode: s.marqueeOverlapMode,
        selectLinkedClipsTogether: s.selectLinkedClipsTogether,
        perActionTargetMode: s.perActionTargetMode,
      }),
    );
  } catch {
    /* ignore */
  }
}

let persistTimer: number | null = null;
function schedulePersist(s: State): void {
  writeLocal(s);
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = window.setTimeout(() => {
    persistTimer = null;
    void putSettings({
      ui: {
        shortcutTargeting: s.shortcutTargeting,
        timelineSnapEnabled: s.timelineSnapEnabled,
        showCursorTimelineGuide: s.showCursorTimelineGuide,
        cursorActionSelectsClip: s.cursorActionSelectsClip,
        marqueeOverlapMode: s.marqueeOverlapMode,
        selectLinkedClipsTogether: s.selectLinkedClipsTogether,
        perActionTargetMode: s.perActionTargetMode,
      },
    }).catch(() => {});
  }, 400);
}

function mergeFromServer(ps: PublicSettings): Partial<State> {
  const raw = ps.ui;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const o = raw as Record<string, unknown>;
  return {
    ...(typeof o.shortcutTargeting === "string"
      ? { shortcutTargeting: o.shortcutTargeting as ShortcutTargetingPolicy }
      : {}),
    ...(typeof o.timelineSnapEnabled === "boolean"
      ? { timelineSnapEnabled: o.timelineSnapEnabled }
      : {}),
    ...(typeof o.showCursorTimelineGuide === "boolean"
      ? { showCursorTimelineGuide: o.showCursorTimelineGuide }
      : {}),
    ...(typeof o.cursorActionSelectsClip === "boolean"
      ? { cursorActionSelectsClip: o.cursorActionSelectsClip }
      : {}),
    ...(o.perActionTargetMode &&
    typeof o.perActionTargetMode === "object" &&
    !Array.isArray(o.perActionTargetMode)
      ? { perActionTargetMode: o.perActionTargetMode as PerActionTargetOverrideMap }
      : {}),
  };
}

export const useEditorSettingsStore = create<State>((set, get) => {
  const local = readLocal();
  return {
    ...defaults,
    ...local.ui,
    perActionTargetMode: local.perActionTargetMode,
    hydrated: false,

    hydrateFromApi: async () => {
      const loc = readLocal();
      try {
        const ps = await fetchSettings();
        const merged = mergeFromServer(ps);
        const pam =
          (merged.perActionTargetMode as PerActionTargetOverrideMap | undefined) ??
          loc.perActionTargetMode;
        set({
          ...defaults,
          ...loc.ui,
          ...merged,
          perActionTargetMode: pam,
          hydrated: true,
        });
        writeLocal(get());
      } catch {
        set({
          ...defaults,
          ...loc.ui,
          perActionTargetMode: loc.perActionTargetMode,
          hydrated: true,
        });
      }
    },

    setUi: (patch) => {
      set((s) => ({ ...s, ...patch }));
      schedulePersist(get());
    },

    setPerActionTargetMode: (id, mode) => {
      set((s) => {
        const next = { ...s.perActionTargetMode };
        if (mode === undefined) delete next[id];
        else next[id] = mode;
        return { perActionTargetMode: next };
      });
      schedulePersist(get());
    },
  };
});

/** Ref for TimelinePanel viewport — zoom anchor reads scrollLeft here. */
export const timelineViewportElRef: { current: HTMLElement | null } = {
  current: null,
};
