import type { TrackType } from "../timeline/types";

export type PointerRegion =
  | "timeline"
  | "ruler"
  | "mediaBin"
  | "preview"
  | "details"
  | "none";

type CursorSnapshot = {
  region: PointerRegion;
  /** Last pointer device position (for recomputing time after zoom/scroll). */
  clientX: number;
  clientY: number;
  hasFinePointer: boolean;
  /** Timeline-only */
  timeAtCursorRaw: number;
  trackIdAtCursor: string | null;
  trackTypeAtCursor: TrackType | null;
  clipIdAtCursor: string | null;
  clipOffsetAtCursor: number | null;
};

const defaultSnap: CursorSnapshot = {
  region: "none",
  clientX: 0,
  clientY: 0,
  hasFinePointer: false,
  timeAtCursorRaw: 0,
  trackIdAtCursor: null,
  trackTypeAtCursor: null,
  clipIdAtCursor: null,
  clipOffsetAtCursor: null,
};

let cursor: CursorSnapshot = { ...defaultSnap };

/** Skip pointermove updates while timeline auto-scrolls during drag */
let ignoreMovesUntil = 0;

export function setIgnoreCursorMovesUntil(ts: number): void {
  ignoreMovesUntil = ts;
}

export function shouldIgnoreCursorPointerMove(): boolean {
  return performance.now() < ignoreMovesUntil;
}

export function updateCursorContextPartial(
  patch: Partial<CursorSnapshot>,
): void {
  cursor = { ...cursor, ...patch };
}

export function getCursorContext(): CursorSnapshot {
  return cursor;
}

export function resetCursorContext(): void {
  cursor = { ...defaultSnap };
}

/** For TimelinePanel visual guide (refs, no React state on move). */
export const cursorVisualRef: {
  guideX: { current: number | null };
  guideVisible: { current: boolean };
  hoverClipId: { current: string | null };
} = {
  guideX: { current: null },
  guideVisible: { current: false },
  hoverClipId: { current: null },
};

export function setCursorVisualGuide(pxFromCanvasLeft: number | null): void {
  cursorVisualRef.guideX.current = pxFromCanvasLeft;
  cursorVisualRef.guideVisible.current = pxFromCanvasLeft !== null;
}

export function setCursorHoverClip(clipId: string | null): void {
  cursorVisualRef.hoverClipId.current = clipId;
}
