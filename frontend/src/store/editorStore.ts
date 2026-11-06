import { create } from "zustand";
import { fetchFootageList, type FootageClip } from "../api/footage";

type EditorState = {
  planName: string;
  setPlanName: (name: string) => void;

  footageClips: FootageClip[];
  footageLoading: boolean;
  footageError: string | null;
  selectedFootageName: string | null;

  fetchFootage: () => Promise<void>;
  selectFootage: (name: string) => void;
  selectedFootage: () => FootageClip | null;
};

export const useEditorStore = create<EditorState>((set, get) => ({
  planName: "draft1",
  setPlanName: (name) => set({ planName: name }),

  footageClips: [],
  footageLoading: false,
  footageError: null,
  selectedFootageName: null,

  fetchFootage: async () => {
    set({ footageLoading: true, footageError: null });
    try {
      const clips = await fetchFootageList();
      set({ footageClips: clips, footageLoading: false });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      set({ footageLoading: false, footageError: message });
    }
  },

  selectFootage: (name) => set({ selectedFootageName: name }),

  selectedFootage: () => {
    const { footageClips, selectedFootageName } = get();
    if (!selectedFootageName) return null;
    return footageClips.find((c) => c.name === selectedFootageName) ?? null;
  },
}));

/** Hook helper — re-renders when selection changes. */
export function useSelectedFootage(): FootageClip | null {
  const name = useEditorStore((s) => s.selectedFootageName);
  const clips = useEditorStore((s) => s.footageClips);
  if (!name) return null;
  return clips.find((c) => c.name === name) ?? null;
}
