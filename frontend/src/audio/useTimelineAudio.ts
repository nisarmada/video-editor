/**
 * Timeline preview audio: Web Audio API + pooled <audio> elements.
 *
 * Why <audio> + MediaElementAudioSourceNode (not AudioBuffer decode):
 * - The browser streams over HTTP with byte-range requests; nothing decodes the full
 *   file into JS heap, so long files stay efficient.
 * - A small pool caps simultaneous decode streams (overlapping clips / different sources).
 *
 * Master clock: the preview <video> element drives timeline playhead during video clips
 * (timeupdate → setPlayheadSeconds). This hook follows that playhead. For the embedded
 * voice that matches the active video clip, we snap pooled audio currentTime to
 * video.currentTime when drift exceeds ~80ms (video wins for that path). Other voices
 * follow computed source times from playhead.
 */

import { useEffect, useRef, type RefObject } from "react";
import {
  CLIP_END_SLACK,
  clipTimelineDuration,
  timelineToSourceSeconds,
  proxyUrlFromSource,
} from "../timeline/duration";
import { duckFactorForTrack } from "../timeline/duckEnvelope";
import { audioFadeGainAt } from "../timeline/previewFades";
import type { TimelineTrack } from "../timeline/types";
import type { TimelineClip, TimelineV2 } from "../timeline/types";
import { useTimelineStore } from "../store/timelineStore";
import {
  ensureMediaElementSource,
  teardownMediaElementWire,
} from "./timelineAudioGraph";

const POOL_SIZE = 16;
const DRIFT_RESYNC_S = 0.08;
const PRELOAD_AHEAD_S = 2.5;

type Pooled = {
  audio: HTMLAudioElement;
  proxyUrl: string | null;
  /** Which timeline voice uses this slot (video:id or audio:id). */
  boundKey: string | null;
};

export type TimelineAudioOptions = {
  videoRef: RefObject<HTMLVideoElement | null>;
  masterVolume: number;
  masterMuted: boolean;
};

type ActiveVoice = {
  key: string;
  proxyUrl: string;
  clip: TimelineClip;
  track: TimelineTrack;
  trackType: "video" | "audio";
  syncToVideo: boolean;
  trackVolume: number;
};

function activeVideoClipAtTime(
  timeline: TimelineV2,
  t: number,
): TimelineClip | null {
  const tagged: { clip: TimelineClip; trackIndex: number }[] = [];
  timeline.tracks.forEach((tr, trackIndex) => {
    if (tr.type !== "video") return;
    for (const c of tr.clips ?? []) {
      tagged.push({ clip: c, trackIndex });
    }
  });
  tagged.sort((a, b) => {
    const d = a.clip.timeline_start - b.clip.timeline_start;
    if (d !== 0) return d;
    return a.trackIndex - b.trackIndex;
  });
  let best: TimelineClip | null = null;
  let bestKey: [number, number] = [-Infinity, -1];
  tagged.forEach(({ clip: c }, order) => {
    const dur = clipTimelineDuration(c, "video");
    const start = c.timeline_start;
    const end = start + dur;
    if (t >= start - 1e-9 && t < end + CLIP_END_SLACK) {
      const key: [number, number] = [start, order];
      if (
        best === null ||
        key[0] > bestKey[0] + 1e-9 ||
        (Math.abs(key[0] - bestKey[0]) <= 1e-9 && key[1] > bestKey[1])
      ) {
        best = c;
        bestKey = key;
      }
    }
  });
  return best;
}

function activeAudioVoices(
  timeline: TimelineV2,
  t: number,
  activeVideo: TimelineClip | null,
): ActiveVoice[] {
  const eps = 1e-5;
  const voices: ActiveVoice[] = [];

  for (const tr of timeline.tracks ?? []) {
    const ttype = tr.type;
    if (ttype !== "video" && ttype !== "audio") continue;
    if (tr.muted) continue;

    for (const clip of tr.clips ?? []) {
      if (!clip.source) continue;
      const dur = clipTimelineDuration(clip, ttype);
      const end = clip.timeline_start + dur;
      if (t < clip.timeline_start - eps || t >= end - eps) continue;

      const trackVol =
        typeof tr.volume === "number" && Number.isFinite(tr.volume)
          ? tr.volume
          : 1;

      if (ttype === "video") {
        if (clip.audio_source === "detached") continue;
        voices.push({
          key: `v:${clip.id}`,
          proxyUrl: proxyUrlFromSource(clip.source),
          clip,
          track: tr,
          trackType: "video",
          syncToVideo: activeVideo?.id === clip.id,
          trackVolume: trackVol,
        });
      } else {
        voices.push({
          key: `a:${clip.id}`,
          proxyUrl: proxyUrlFromSource(clip.source),
          clip,
          track: tr,
          trackType: "audio",
          syncToVideo: false,
          trackVolume: trackVol,
        });
      }
    }
  }

  return voices;
}

function upcomingPreloadUrls(timeline: TimelineV2, t: number): string[] {
  const urls = new Set<string>();
  const horizon = t + PRELOAD_AHEAD_S;

  for (const tr of timeline.tracks ?? []) {
    const ttype = tr.type;
    if (ttype !== "video" && ttype !== "audio") continue;
    if (tr.muted) continue;

    for (const clip of tr.clips ?? []) {
      if (!clip.source) continue;
      const dur = clipTimelineDuration(clip, ttype);
      const start = clip.timeline_start;
      const end = start + dur;
      if (ttype === "video" && clip.audio_source === "detached") continue;
      if (start >= t && start <= horizon && end > t) {
        urls.add(proxyUrlFromSource(clip.source));
      }
    }
  }
  return [...urls];
}

function mediaTimeForVoice(
  voice: ActiveVoice,
  playhead: number,
  video: HTMLVideoElement | null,
): number {
  const { clip, syncToVideo, trackType } = voice;
  const srcIn = clip.source_in ?? 0;
  const srcOut = clip.source_out ?? srcIn;
  const clamp = (s: number) =>
    Math.min(Math.max(s, srcIn), Math.max(srcOut - 1e-3, srcIn));

  if (syncToVideo && video && trackType === "video") {
    let st = video.currentTime;
    if (st < srcIn - 0.05 || st > srcOut + 0.05) {
      st = clamp(timelineToSourceSeconds(clip, playhead));
    }
    return clamp(st);
  }
  return clamp(timelineToSourceSeconds(clip, playhead));
}

export function useTimelineAudio(opts: TimelineAudioOptions): void {
  const { videoRef, masterVolume, masterMuted } = opts;

  const timeline = useTimelineStore((s) => s.timeline);
  const playhead = useTimelineStore((s) => s.playheadSeconds);
  const playing = useTimelineStore((s) => s.timelinePlaying);
  const dragInProgress = useTimelineStore((s) => s.dragInProgress);

  const ctxRef = useRef<AudioContext | null>(null);
  const masterRef = useRef<GainNode | null>(null);
  const poolRef = useRef<Pooled[] | null>(null);
  const wireErrorSentRef = useRef(false);

  useEffect(() => {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;

    const ctx = new Ctor();
    const master = ctx.createGain();
    master.connect(ctx.destination);

    const pool: Pooled[] = [];
    for (let i = 0; i < POOL_SIZE; i++) {
      const audio = document.createElement("audio");
      audio.preload = "auto";
      audio.crossOrigin = "anonymous";
      audio.dataset.poolIdx = String(i);
      pool.push({ audio, proxyUrl: null, boundKey: null });
    }

    ctxRef.current = ctx;
    masterRef.current = master;
    poolRef.current = pool;

    const resume = () => void ctx.resume();
    window.addEventListener("pointerdown", resume, { passive: true });
    window.addEventListener("keydown", resume);

    return () => {
      window.removeEventListener("pointerdown", resume);
      window.removeEventListener("keydown", resume);
      for (const p of pool) {
        p.audio.pause();
        p.audio.removeAttribute("src");
        p.audio.load();
        teardownMediaElementWire(p.audio);
      }
      master.disconnect();
      void ctx.close();
      ctxRef.current = null;
      masterRef.current = null;
      poolRef.current = null;
    };
  }, []);

  useEffect(() => {
    const g = masterRef.current;
    if (!g) return;
    g.gain.value = masterMuted ? 0 : Math.max(0, Math.min(1, masterVolume));
  }, [masterMuted, masterVolume]);

  useEffect(() => {
    if (!playing) return;
    const ctx = ctxRef.current;
    if (ctx && ctx.state !== "running") void ctx.resume();
  }, [playing]);

  useEffect(() => {
    const ctx = ctxRef.current;
    const masterGain = masterRef.current;
    const pool = poolRef.current;
    if (!ctx || !masterGain || !pool || !timeline) return;

    const absUrl = (u: string) => new URL(u, window.location.origin).href;

    const wireSlot = (slot: Pooled): boolean => {
      const node = ensureMediaElementSource(ctx, masterGain, slot.audio);
      if (node) {
        wireErrorSentRef.current = false;
        return true;
      }
      if (!wireErrorSentRef.current) {
        wireErrorSentRef.current = true;
        useTimelineStore.getState().setUiBannerError(
          "Preview audio failed to start (Web Audio). Try refreshing the page.",
        );
      }
      return false;
    };

    const assignSlot = (
      voiceKey: string,
      proxyUrl: string,
      activeKeySet: Set<string>,
    ): Pooled => {
      const wantAbs = absUrl(proxyUrl);
      let slot = pool.find((p) => p.boundKey === voiceKey);
      if (!slot) {
        slot =
          pool.find((p) => p.boundKey === null) ??
          pool.find((p) => p.boundKey && !activeKeySet.has(p.boundKey)) ??
          pool.reduce((a, b) =>
            a.audio.currentTime <= b.audio.currentTime ? a : b,
          );
      }

      if (slot.proxyUrl !== proxyUrl || absUrl(slot.audio.src || "") !== wantAbs) {
        slot.audio.pause();
        slot.audio.src = proxyUrl;
        slot.audio.load();
        slot.proxyUrl = proxyUrl;
        /* Do not disconnect MediaElementAudioSourceNode: each <audio> may only be
         * wired once; changing src is allowed while the same source node is used. */
      }
      slot.boundKey = voiceKey;
      return slot;
    };

    const syncTransport = () => {
      const tl = useTimelineStore.getState().timeline;
      const ph = useTimelineStore.getState().playheadSeconds;
      const pl = useTimelineStore.getState().timelinePlaying;
      const drag = useTimelineStore.getState().dragInProgress;
      const video = videoRef.current;

      if (!tl || !poolRef.current || !ctxRef.current || !masterRef.current) return;

      const activeVid = activeVideoClipAtTime(tl, ph);
      const voices = activeAudioVoices(tl, ph, activeVid);
      const activeKeys = new Set(voices.map((v) => v.key));

      for (const p of poolRef.current) {
        if (p.boundKey && !activeKeys.has(p.boundKey)) {
          p.audio.pause();
          p.boundKey = null;
        }
      }

      const scrubSilent = drag;

      for (const voice of voices) {
        const slot = assignSlot(voice.key, voice.proxyUrl, activeKeys);
        if (!wireSlot(slot)) {
          continue;
        }
        const { clip } = voice;
        const speed = clip.speed && clip.speed > 0 ? clip.speed : 1;
        const cvol = clip.volume !== undefined ? clip.volume : 1;
        const tv = voice.trackVolume;

        slot.audio.playbackRate = speed;
        const fadeG = audioFadeGainAt(clip, voice.trackType, ph);
        const duck =
          voice.trackType === "audio"
            ? duckFactorForTrack(tl, voice.track, ph)
            : 1;
        slot.audio.volume = Math.max(
          0,
          Math.min(1, cvol * tv * fadeG * duck),
        );

        const mt = mediaTimeForVoice(voice, ph, video);

        if (scrubSilent || !pl) {
          slot.audio.pause();
          if (!scrubSilent) {
            if (Math.abs(slot.audio.currentTime - mt) > 0.02) {
              slot.audio.currentTime = mt;
            }
          }
          continue;
        }

        if (voice.syncToVideo && video) {
          if (Math.abs(slot.audio.currentTime - video.currentTime) > DRIFT_RESYNC_S) {
            slot.audio.currentTime = video.currentTime;
          }
        } else if (Math.abs(slot.audio.currentTime - mt) > DRIFT_RESYNC_S) {
          slot.audio.currentTime = mt;
        }

        void slot.audio.play().catch(() => {
          /* Clock keeps running; missing proxy/decoding is surfaced on the video element. */
        });
      }
    };

    let raf = 0;
    const loop = () => {
      syncTransport();
      if (
        useTimelineStore.getState().timelinePlaying &&
        !useTimelineStore.getState().dragInProgress
      ) {
        raf = requestAnimationFrame(loop);
      }
    };

    syncTransport();
    if (playing && !dragInProgress) {
      raf = requestAnimationFrame(loop);
    }

    return () => cancelAnimationFrame(raf);
  }, [timeline, playhead, playing, dragInProgress, videoRef]);

  // Preload: warm decode for URLs starting soon
  useEffect(() => {
    const pool = poolRef.current;
    if (!pool || !timeline) return;

    for (const url of upcomingPreloadUrls(timeline, playhead)) {
      if (pool.some((p) => p.proxyUrl === url && p.audio.readyState >= 2)) {
        continue;
      }
      const free = pool.find((p) => !p.boundKey && !p.audio.src);
      if (!free) break;
      free.audio.src = url;
      free.audio.load();
      free.proxyUrl = url;
    }
  }, [timeline, playhead]);
}
