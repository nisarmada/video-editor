import type { ProjectCanvas, TimelineSettings } from "./types";

export type CanvasPresetId =
  | "9:16"
  | "1:1"
  | "4:5"
  | "16:9"
  | "21:9"
  | "custom";

export type ResolutionTier = "720p" | "1080p" | "1440p" | "4K";

/** Even dimensions for H.264 (matches scripts/canvas_settings.even_dimension). */
export function evenDimension(n: number): number {
  const v = Math.max(2, Math.round(n));
  return v % 2 === 0 ? v : v + 1;
}

const SHORT_EDGE: Record<ResolutionTier, number> = {
  "720p": 720,
  "1080p": 1080,
  "1440p": 1440,
  "4K": 2160,
};

/** Base aspect (width : height) at 1080 short-edge reference for presets. */
const PRESET_BASE: Record<
  Exclude<CanvasPresetId, "custom">,
  { w: number; h: number; label: string }
> = {
  "9:16": { w: 1080, h: 1920, label: "Vertical 9:16" },
  "1:1": { w: 1080, h: 1080, label: "Square 1:1" },
  "4:5": { w: 1080, h: 1350, label: "Portrait 4:5" },
  "16:9": { w: 1920, h: 1080, label: "Landscape 16:9" },
  "21:9": { w: 2520, h: 1080, label: "Ultrawide 21:9" },
};

export function scaledPresetSize(
  preset: Exclude<CanvasPresetId, "custom">,
  tier: ResolutionTier,
): { width: number; height: number } {
  const base = PRESET_BASE[preset];
  const short = Math.min(base.w, base.h);
  const scale = SHORT_EDGE[tier] / short;
  return {
    width: evenDimension(base.w * scale),
    height: evenDimension(base.h * scale),
  };
}

export const CANVAS_FPS_OPTIONS = [24, 25, 30, 50, 60] as const;

export const DEFAULT_PROJECT_CANVAS: ProjectCanvas = {
  width: 1080,
  height: 1920,
  fps: 30,
  fit: "contain",
  bar_fill: "black",
  fit_position_x: 0.5,
  fit_position_y: 0.5,
};

export function resolveProjectCanvas(
  settings: TimelineSettings | undefined | null,
): ProjectCanvas {
  const s = settings ?? {};
  const block = s.canvas ?? {};
  const width = evenDimension(
    block.width ?? s.width ?? DEFAULT_PROJECT_CANVAS.width!,
  );
  const height = evenDimension(
    block.height ?? s.height ?? DEFAULT_PROJECT_CANVAS.height!,
  );
  const fps =
    block.fps ?? s.fps ?? DEFAULT_PROJECT_CANVAS.fps ?? 30;
  const fit = block.fit === "cover" ? "cover" : "contain";
  const bar_fill = block.bar_fill === "blur" ? "blur" : "black";
  const fit_position_x =
    block.fit_position_x ?? DEFAULT_PROJECT_CANVAS.fit_position_x ?? 0.5;
  const fit_position_y =
    block.fit_position_y ?? DEFAULT_PROJECT_CANVAS.fit_position_y ?? 0.5;
  return {
    width,
    height,
    fps,
    fit,
    bar_fill,
    fit_position_x,
    fit_position_y,
  };
}

export function canvasAspectRatio(canvas: ProjectCanvas): number {
  const w = canvas.width ?? 1080;
  const h = canvas.height ?? 1920;
  return w / h;
}

export function oddDimensionWarning(canvas: ProjectCanvas): string | null {
  const rawW = canvas.width ?? 1080;
  const rawH = canvas.height ?? 1920;
  if (rawW % 2 === 0 && rawH % 2 === 0) return null;
  return `Odd dimension(s) rounded to ${evenDimension(rawW)}×${evenDimension(rawH)} for H.264.`;
}

/** Rough MB estimate from duration, pixels, fps, and CRF (not exact). */
export function estimateExportSizeMb(
  durationSec: number,
  canvas: ProjectCanvas,
  crf: number,
): number {
  const pixels = (canvas.width ?? 1080) * (canvas.height ?? 1920);
  const fps = canvas.fps ?? 30;
  const ref = 1080 * 1920 * 30;
  const scale = (pixels * fps) / ref;
  const crfFactor = Math.pow(1.08, 23 - crf);
  const mbPerSec = 0.35 * scale * crfFactor;
  return Math.max(0.1, durationSec * mbPerSec);
}

export function presetList(): {
  id: Exclude<CanvasPresetId, "custom">;
  label: string;
}[] {
  return (Object.keys(PRESET_BASE) as Exclude<CanvasPresetId, "custom">[]).map(
    (id) => ({ id, label: PRESET_BASE[id].label }),
  );
}

export function detectPreset(
  width: number,
  height: number,
): CanvasPresetId {
  for (const id of Object.keys(PRESET_BASE) as Exclude<
    CanvasPresetId,
    "custom"
  >[]) {
    const b = PRESET_BASE[id];
    const ar = b.w / b.h;
    const ar2 = width / height;
    if (Math.abs(ar - ar2) < 0.02 && (b.w === width || b.h === height)) {
      return id;
    }
  }
  return "custom";
}
