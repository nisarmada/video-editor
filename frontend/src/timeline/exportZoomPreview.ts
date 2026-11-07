/**
 * Matches export punch-in after letterbox normalize (scripts/media.py _zoom_punch_filter).
 * Preview uses CSS scale on the letterboxed proxy — not bit-identical to FFmpeg, but
 * same center crop semantics when zoom > 1.
 */
export function previewPunchInScale(zoom: number | undefined): number {
  const z = zoom ?? 1;
  if (!Number.isFinite(z) || z <= 1.001) return 1;
  return z;
}
