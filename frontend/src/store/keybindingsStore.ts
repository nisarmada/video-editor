import { create } from "zustand";
import type { KeybindingOverridesMap } from "../shortcuts/types";
import { fetchSettings, putSettings } from "../api/settings";

const LS_KEY = "video-editor-keybindings-overrides";

function readLocalOverrides(): KeybindingOverridesMap {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return {};
    const j = JSON.parse(raw) as unknown;
    return typeof j === "object" && j !== null && !Array.isArray(j) ? (j as KeybindingOverridesMap) : {};
  } catch {
    return {};
  }
}

function writeLocalOverrides(o: KeybindingOverridesMap): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(o));
  } catch {
    /* ignore */
  }
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;

function schedulePersistToServer(overrides: KeybindingOverridesMap): void {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    persistTimer = null;
    void putSettings({ keybindings: overrides }).catch(() => {
      /* keep localStorage copy; will retry on next save */
    });
  }, 400);
}

type KeybindingsState = {
  overrides: KeybindingOverridesMap;
  /** True after first attempted sync from API (success or fail) */
  hydratedFromApi: boolean;
  shortcutCaptureActive: boolean;
  cheatSheetOpen: boolean;
  keyboardSettingsOpen: boolean;

  setShortcutCaptureActive: (v: boolean) => void;
  setCheatSheetOpen: (v: boolean) => void;
  setKeyboardSettingsOpen: (v: boolean) => void;

  hydrateFromApi: () => Promise<void>;
  setOverrides: (next: KeybindingOverridesMap) => void;
  setActionBindings: (actionId: string, bindings: BindingChordList) => void;
  resetAction: (actionId: string) => void;
  resetAll: () => void;
};

type BindingChordList = import("../shortcuts/types").BindingChord[] | [];

export const useKeybindingsStore = create<KeybindingsState>((set, get) => ({
  overrides: readLocalOverrides(),
  hydratedFromApi: false,
  shortcutCaptureActive: false,
  cheatSheetOpen: false,
  keyboardSettingsOpen: false,

  setShortcutCaptureActive: (v) => set({ shortcutCaptureActive: v }),
  setCheatSheetOpen: (v) => set({ cheatSheetOpen: v }),
  setKeyboardSettingsOpen: (v) => set({ keyboardSettingsOpen: v }),

  hydrateFromApi: async () => {
    const local = readLocalOverrides();
    try {
      const s = await fetchSettings();
      const kb = s.keybindings;
      if (kb && typeof kb === "object" && !Array.isArray(kb)) {
        const o = kb as KeybindingOverridesMap;
        const merged = { ...local, ...o };
        set({ overrides: merged, hydratedFromApi: true });
        writeLocalOverrides(merged);
      } else {
        set({ overrides: local, hydratedFromApi: true });
      }
    } catch {
      set({ overrides: local, hydratedFromApi: true });
    }
  },

  setOverrides: (next) => {
    set({ overrides: next });
    writeLocalOverrides(next);
    schedulePersistToServer(next);
  },

  setActionBindings: (actionId, bindings) => {
    const prev = get().overrides;
    const next = { ...prev };
    if (Array.isArray(bindings) && bindings.length === 0) {
      next[actionId] = [];
    } else {
      next[actionId] = bindings as import("../shortcuts/types").BindingChord[];
    }
    get().setOverrides(next);
  },

  resetAction: (actionId) => {
    const next = { ...get().overrides };
    delete next[actionId];
    get().setOverrides(next);
  },

  resetAll: () => {
    get().setOverrides({});
  },
}));
