import { create } from "zustand";

export type WaveformPayload = {
  has_audio: boolean;
  duration: number;
  sample_rate_hz_of_peaks: number;
  peaks: [number, number][];
};

export type CachedWaveform =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "processing" }
  | { kind: "failed"; error?: string }
  | { kind: "no_audio" }
  | { kind: "ready"; data: WaveformPayload };

type State = {
  bySource: Record<string, CachedWaveform>;
  ensureFetch: (source: string) => void;
};

const inFlight = new Set<string>();

function basenameFromFootageSource(source: string): string | null {
  if (!source.includes("footage/")) return null;
  const name = source.split("/").pop();
  return name && name.length > 0 ? name : null;
}

export const useWaveformCacheStore = create<State>((set, get) => ({
  bySource: {},

  ensureFetch: (source: string) => {
    const cur = get().bySource[source];
    if (cur?.kind === "ready" || cur?.kind === "no_audio") return;
    if (inFlight.has(source)) return;

    const base = basenameFromFootageSource(source);
    if (!base) {
      set((s) => ({
        bySource: { ...s.bySource, [source]: { kind: "no_audio" } },
      }));
      return;
    }

    inFlight.add(source);
    set((s) => ({
      bySource: { ...s.bySource, [source]: { kind: "loading" } },
    }));

    const url = `/api/footage/${encodeURIComponent(base)}/waveform`;

    const finish = (w: CachedWaveform) => {
      inFlight.delete(source);
      set((s) => ({ bySource: { ...s.bySource, [source]: w } }));
    };

    const poll = () => {
      void (async () => {
        try {
          const res = await fetch(url);
          if (!res.ok) {
            finish({ kind: "failed", error: await res.text() });
            return;
          }
          const j = (await res.json()) as {
            status?: string;
            error?: string;
            has_audio?: boolean;
            duration?: number;
            sample_rate_hz_of_peaks?: number;
            peaks?: [number, number][];
          };

          if (j.status === "processing") {
            set((s) => ({
              bySource: { ...s.bySource, [source]: { kind: "processing" } },
            }));
            window.setTimeout(poll, 500);
            return;
          }
          if (j.status === "failed") {
            finish({ kind: "failed", error: j.error });
            return;
          }
          if (j.has_audio === false) {
            finish({ kind: "no_audio" });
            return;
          }
          finish({
            kind: "ready",
            data: {
              has_audio: true,
              duration: j.duration ?? 0,
              sample_rate_hz_of_peaks: j.sample_rate_hz_of_peaks ?? 100,
              peaks: j.peaks ?? [],
            },
          });
        } catch (e) {
          finish({
            kind: "failed",
            error: e instanceof Error ? e.message : "fetch error",
          });
        }
      })();
    };

    poll();
  },
}));
