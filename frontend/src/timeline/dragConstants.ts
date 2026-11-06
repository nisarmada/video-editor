/** Matches scripts/timeline_format.MIN_CLIP_SECONDS — server rejects shorter spans. */
export const MIN_CLIP_SECONDS = 0.3;

export const TIMELINE_SNAP_SEC = 0.1;

export const FOOTAGE_DRAG_MIME = "application/x-video-editor-footage";

/** Same JSON as FOOTAGE_DRAG_MIME — WebKit/Safari often omits custom types in drop.getData; use this fallback. */
export const FOOTAGE_DRAG_TEXT_TYPE = "text/plain";
