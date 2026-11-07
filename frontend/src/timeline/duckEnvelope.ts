import { clipTimelineDuration } from "./duration";
import type { TimelineTrack, TimelineV2 } from "./types";

/** Match scripts/edit_vocab.py DUCK_ATTACK_S / DUCK_RELEASE_S. */
export const DUCK_ATTACK_S = 0.08;
export const DUCK_RELEASE_S = 0.25;
export const DUCK_GAIN_DEFAULT = 0.25;

export type DuckWindow = { start: number; end: number };

function windowFactor(
  t: number,
  start: number,
  end: number,
  duckGain: number,
  attack: number,
  release: number,
): number {
  const span = end - start;
  if (span <= 1e-4) return 1;
  if (t < start || t >= end) return 1;
  const attackS = Math.min(Math.max(attack, 0), span / 2);
  const releaseS = Math.min(Math.max(release, 0), Math.max(span - attackS, 0));
  if (attackS > 1e-4 && t < start + attackS) {
    return 1 + (duckGain - 1) * ((t - start) / attackS);
  }
  if (t < end - releaseS) return duckGain;
  if (releaseS <= 1e-4) return duckGain;
  return duckGain + (1 - duckGain) * ((t - (end - releaseS)) / releaseS);
}

/** 1 outside every window, ducked inside, with linear attack and release. */
export function duckFactorAt(
  t: number,
  windows: DuckWindow[],
  duckGain: number,
  attack = DUCK_ATTACK_S,
  release = DUCK_RELEASE_S,
): number {
  let factor = 1;
  for (const window of windows) {
    factor = Math.min(
      factor,
      windowFactor(t, window.start, window.end, duckGain, attack, release),
    );
  }
  return factor;
}

/**
 * Preview gain for an audio track that ducks under another track.
 * `t` is the playhead. Windows are absolute timeline times of the under track.
 */
export function duckFactorForTrack(
  timeline: TimelineV2,
  track: TimelineTrack,
  playhead: number,
): number {
  const underId = track.duck_under_track_id?.trim();
  if (!underId) return 1;
  const under = (timeline.tracks ?? []).find((item) => item.id === underId);
  if (!under) return 1;
  const gain =
    typeof track.duck_gain === "number" && Number.isFinite(track.duck_gain)
      ? track.duck_gain
      : DUCK_GAIN_DEFAULT;
  const windows: DuckWindow[] = [];
  for (const clip of under.clips ?? []) {
    const dur = clipTimelineDuration(clip, under.type);
    windows.push({ start: clip.timeline_start, end: clip.timeline_start + dur });
  }
  return duckFactorAt(playhead, windows, gain);
}
