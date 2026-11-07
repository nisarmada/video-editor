import type { TimelineClip } from "./types";
import { clipTimelineDuration } from "./duration";

/** Preview envelope when explicit fade fields are set (export uses richer legacy defaults). */
export function audioFadeGainAt(
  clip: TimelineClip,
  trackType: string,
  playhead: number,
): number {
  const dur = clipTimelineDuration(clip, trackType);
  const tIn = playhead - clip.timeline_start;
  if (tIn < 0 || tIn >= dur) return 0;
  let g = 1;
  if (clip.audio_fade_in != null && clip.audio_fade_in > 0) {
    g *= Math.min(1, Math.max(0, tIn / clip.audio_fade_in));
  }
  if (clip.audio_fade_out != null && clip.audio_fade_out > 0) {
    const remain = dur - tIn;
    g *= Math.min(1, Math.max(0, remain / clip.audio_fade_out));
  }
  return g;
}

export function videoFadeOpacityAt(
  clip: TimelineClip,
  playhead: number,
): number {
  const dur = clipTimelineDuration(clip, "video");
  const tIn = playhead - clip.timeline_start;
  if (tIn < 0 || tIn >= dur) return 0;
  let o = 1;
  if (clip.video_fade_in != null && clip.video_fade_in > 0) {
    o *= Math.min(1, Math.max(0, tIn / clip.video_fade_in));
  }
  if (clip.video_fade_out != null && clip.video_fade_out > 0) {
    const remain = dur - tIn;
    o *= Math.min(1, Math.max(0, remain / clip.video_fade_out));
  }
  return o;
}
