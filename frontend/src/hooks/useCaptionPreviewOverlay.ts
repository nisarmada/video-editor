import { useEffect, useRef } from "react";
import JASSUB from "jassub";
import { postCaptionsAss } from "../api/captions";
import {
  JASSUB_DEFAULT_WOFF2_URL,
  JASSUB_LEGACY_WASM_URL,
  JASSUB_MODERN_WASM_URL,
  JASSUB_WASM_URL,
  JASSUB_WORKER_URL,
} from "../lib/jassubAssets";
import {
  activeVideoClipAt,
  getSortedVideoClips,
} from "../timeline/duration";
import type { TimelineV2 } from "../timeline/types";

/** Lowercase family key -> TTF basename under /api/fonts/dir/ */
const FONT_FILES: Record<string, string> = {
  "bebas neue": "BebasNeue-Regular.ttf",
  bangers: "Bangers-Regular.ttf",
  oswald: "Oswald-Variable.ttf",
  inter: "Inter-Variable.ttf",
  anton: "Anton-Regular.ttf",
  poppins: "Poppins-Regular.ttf",
  montserrat: "Montserrat-Variable.ttf",
  arial: "Poppins-Regular.ttf",
};

function availableFontsMap(): Record<string, string> {
  const out: Record<string, string> = {
    "liberation sans": JASSUB_DEFAULT_WOFF2_URL,
  };
  for (const [key, file] of Object.entries(FONT_FILES)) {
    out[key] = `/api/fonts/dir/${encodeURIComponent(file)}`;
  }
  return out;
}

type Args = {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  timeline: TimelineV2 | null;
  playheadSeconds: number;
  previewClipOnly: boolean;
  selectedClipId: string | null;
  enabled: boolean;
  debounceMs: number;
};

/**
 * Renders ASS from POST /api/captions/ass over the video with JASSUB, synced to media time
 * via timeOffset (timeline seconds − source seconds at clip start).
 */
export function useCaptionPreviewOverlay({
  videoRef,
  timeline,
  playheadSeconds,
  previewClipOnly,
  selectedClipId,
  enabled,
  debounceMs,
}: Args) {
  const jassubRef = useRef<InstanceType<typeof JASSUB> | null>(null);
  const buildingRef = useRef(false);
  const requestIdRef = useRef(0);

  const clips = timeline ? getSortedVideoClips(timeline) : [];
  const activeClip = activeVideoClipAt(clips, playheadSeconds);
  const clipId = activeClip?.id ?? null;

  // Recreate renderer when the underlying video element or clip context changes.
  useEffect(() => {
    const video = videoRef.current;
    if (!enabled || !video || !timeline || !clipId || !activeClip) {
      if (jassubRef.current) {
        jassubRef.current.destroy();
        jassubRef.current = null;
      }
      return;
    }

    const srcIn = activeClip.source_in ?? 0;
    const timelineOffset = activeClip.timeline_start - srcIn;

    const j = new JASSUB({
      video,
      workerUrl: JASSUB_WORKER_URL,
      wasmUrl: JASSUB_WASM_URL,
      legacyWasmUrl: JASSUB_LEGACY_WASM_URL,
      modernWasmUrl: JASSUB_MODERN_WASM_URL,
      availableFonts: availableFontsMap(),
      fallbackFont: "liberation sans",
      useLocalFonts: false,
      timeOffset: timelineOffset,
      // Match export: libass draws blur for neon animation.
      dropAllBlur: false,
      subContent: `[Script Info]\nTitle: placeholder\n\n[V4+ Styles]\n\n[Events]\n`,
    });
    jassubRef.current = j;

    return () => {
      j.destroy();
      if (jassubRef.current === j) {
        jassubRef.current = null;
      }
    };
  }, [enabled, videoRef, timeline, clipId, activeClip]);

  // Debounced ASS regeneration (same generator as export).
  useEffect(() => {
    const video = videoRef.current;
    const inst = jassubRef.current;
    if (!enabled || !timeline || !video || !inst || !clipId || !activeClip) {
      return;
    }

    const id = ++requestIdRef.current;
    const t = window.setTimeout(() => {
      void (async () => {
        if (buildingRef.current) return;
        buildingRef.current = true;
        try {
          const scopeClip =
            previewClipOnly && selectedClipId ? selectedClipId : null;
          const { ass } = await postCaptionsAss({
            timeline,
            clip_ids: scopeClip ? [scopeClip] : undefined,
            style_target: scopeClip ? "clip" : "plan",
            style_clip_id: scopeClip ?? undefined,
          });
          if (requestIdRef.current !== id) return;
          inst.setTrack(ass);
        } catch (e) {
          console.warn("Caption preview ASS failed:", e);
        } finally {
          buildingRef.current = false;
        }
      })();
    }, debounceMs);

    return () => window.clearTimeout(t);
  }, [
    enabled,
    timeline,
    videoRef,
    clipId,
    activeClip,
    previewClipOnly,
    selectedClipId,
    debounceMs,
  ]);

  return jassubRef;
}
