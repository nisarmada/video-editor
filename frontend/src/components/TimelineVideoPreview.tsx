import { useEffect, useMemo, useRef, useState } from "react";
import { useTimelineAudio } from "../audio/useTimelineAudio";
import {
  activeVideoClipAt,
  clipTimelineDuration,
  clipDisplayName,
  getSortedVideoClips,
  proxyUrlFromSource,
  timelineEnd,
  timelineToSourceSeconds,
} from "../timeline/duration";
import { useCaptionPreviewOverlay } from "../hooks/useCaptionPreviewOverlay";
import { useTimelineStore } from "../store/timelineStore";
import { formatTimecode } from "../utils/timeFormat";
import { useKeybindingsStore } from "../store/keybindingsStore";
import { useEditorSettingsStore } from "../store/editorSettingsStore";
import { getBindingLabel, getBindingTitle } from "../shortcuts/tooltip";

const SOURCE_END_EPS = 0.05;

export default function TimelineVideoPreview() {
  useEditorSettingsStore((s) => s.shortcutTargeting);
  useEditorSettingsStore((s) => s.perActionTargetMode);
  const timeline = useTimelineStore((s) => s.timeline);
  const playhead = useTimelineStore((s) => s.playheadSeconds);
  const playing = useTimelineStore((s) => s.timelinePlaying);
  const togglePlaying = useTimelineStore((s) => s.toggleTimelinePlaying);
  const previewClipOnly = useTimelineStore((s) => s.captionPreviewClipOnly);
  const selectedClipId = useTimelineStore((s) => s.selectedClipId);
  const safeAreaGuide = useTimelineStore((s) => s.captionSafeAreaGuide);

  const videoRef = useRef<HTMLVideoElement>(null);
  const prevClipIdRef = useRef<string | null>(null);
  const [audioMasterVolume, setAudioMasterVolume] = useState(1);
  const [audioMasterMuted, setAudioMasterMuted] = useState(false);

  useTimelineAudio({
    videoRef,
    masterVolume: audioMasterVolume,
    masterMuted: audioMasterMuted,
  });
  const clipsRef = useRef(getSortedVideoClips(timeline));
  clipsRef.current = getSortedVideoClips(timeline);

  const sortedClips = useMemo(
    () => getSortedVideoClips(timeline),
    [timeline],
  );

  const duration = useMemo(
    () => (timeline ? timelineEnd(timeline) : 0),
    [timeline],
  );

  const activeClip = useMemo(
    () => activeVideoClipAt(sortedClips, playhead),
    [sortedClips, playhead],
  );

  const clipId = activeClip?.id ?? null;
  const proxyUrl = activeClip?.source
    ? proxyUrlFromSource(activeClip.source)
    : null;

  useCaptionPreviewOverlay({
    videoRef,
    timeline,
    playheadSeconds: playhead,
    previewClipOnly,
    selectedClipId,
    enabled: true,
    debounceMs: 280,
  });

  // Load proxy / seek when clip or paused scrub position changes (not every tick while playing).
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !timeline) return;

    if (!activeClip || !proxyUrl) {
      video.pause();
      if (video.src) {
        video.removeAttribute("src");
        video.load();
      }
      return;
    }

    const wantTime = timelineToSourceSeconds(activeClip, playhead);
    const srcIn = activeClip.source_in ?? 0;
    const srcOut = activeClip.source_out ?? srcIn;
    const clamped = Math.min(
      Math.max(wantTime, srcIn),
      Math.max(srcOut - 1e-3, srcIn),
    );

    const absUrl = new URL(proxyUrl, window.location.origin).href;
    const needNewSrc = !video.src || video.src !== absUrl;
    const clipChanged = clipId !== prevClipIdRef.current;
    prevClipIdRef.current = clipId;

    const doSeek = () => {
      if (Math.abs(video.currentTime - clamped) > 0.04) {
        video.currentTime = clamped;
      }
    };

    if (!playing) {
      video.pause();
    }

    if (needNewSrc) {
      video.src = proxyUrl;
      video.load();
      const onReady = () => {
        video.removeEventListener("loadedmetadata", onReady);
        doSeek();
      };
      video.addEventListener("loadedmetadata", onReady);
    } else {
      // Same proxy URL: still seek when scrubbing (paused) or when the active clip changed
      // (e.g. two timeline clips from the same file). Avoid seeking every frame while playing
      // and the clip is unchanged — timeupdate keeps the playhead in sync.
      if (!playing || clipChanged) {
        doSeek();
      }
    }
  }, [timeline, clipId, proxyUrl, playing, playhead, activeClip]);

  /**
   * Single transport: `timelinePlaying` drives <video> only (no play()/pause() from rAF or timeupdate).
   * Seek effect loads src + currentTime; this effect starts/stops playback when the proxy is ready.
   */
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const syncFromStore = () => {
      const pl = useTimelineStore.getState().timelinePlaying;
      const hasClip = !!activeClip && !!proxyUrl;
      if (!pl || !hasClip) {
        video.pause();
        return;
      }
      const absWant = new URL(proxyUrl!, window.location.origin).href;
      if (!video.src || video.src !== absWant) {
        return;
      }
      void video.play().catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        useTimelineStore.getState().setTimelinePlaying(false);
      });
    };

    video.addEventListener("loadedmetadata", syncFromStore);
    syncFromStore();

    return () => {
      video.removeEventListener("loadedmetadata", syncFromStore);
    };
  }, [playing, activeClip, proxyUrl, clipId]);

  // While playing inside a clip, don't fight timeupdate with seeks.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onTimeUpdate = () => {
      if (!useTimelineStore.getState().timelinePlaying) return;
      const clips = clipsRef.current;
      const p = useTimelineStore.getState().playheadSeconds;
      const clip = activeVideoClipAt(clips, p);
      if (!clip) return;

      const speed = clip.speed && clip.speed > 0 ? clip.speed : 1;
      const srcIn = clip.source_in ?? 0;
      const srcOut = clip.source_out ?? srcIn;
      const st = video.currentTime;

      if (st >= srcOut - SOURCE_END_EPS) {
        const atEnd =
          clip.timeline_start + clipTimelineDuration(clip, "video");
        const tl = useTimelineStore.getState().timeline;
        const maxT = tl ? timelineEnd(tl) : atEnd;
        useTimelineStore.getState().setPlayheadSeconds(Math.min(atEnd, maxT));
        return;
      }

      const ph = clip.timeline_start + (st - srcIn) / speed;
      useTimelineStore.getState().setPlayheadSeconds(ph);
    };

    video.addEventListener("timeupdate", onTimeUpdate);
    return () => video.removeEventListener("timeupdate", onTimeUpdate);
  }, [timeline]);

  // Drive playhead in gaps + ensure video plays in clips.
  useEffect(() => {
    if (!playing || !timeline) return;

    let raf = 0;
    let last = performance.now();

    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;

      const p = useTimelineStore.getState().playheadSeconds;
      const clip = activeVideoClipAt(clipsRef.current, p);
      const video = videoRef.current;

      if (clip) {
        /* Video play/pause is owned by timelinePlaying sync effect — not here. */
        raf = requestAnimationFrame(step);
        return;
      }

      if (video) video.pause();

      const maxT = timelineEnd(timeline);
      const next = p + dt;
      if (next >= maxT - 1e-6) {
        useTimelineStore.getState().setPlayheadSeconds(maxT);
        useTimelineStore.getState().setTimelinePlaying(false);
        return;
      }
      useTimelineStore.getState().setPlayheadSeconds(next);
      raf = requestAnimationFrame(step);
    };

    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, timeline]);

  const kbOverrides = useKeybindingsStore((s) => s.overrides);
  const playPauseTitle = getBindingTitle("play_pause", kbOverrides);

  const onToggle = () => togglePlaying();

  if (!timeline) {
    return (
      <div className="preview-empty">Load a timeline to preview playback.</div>
    );
  }

  const inGap = !activeClip;

  return (
    <div className="timeline-video-preview">
      <div className="source-preview__meta">
        <span className="source-preview__filename" title={activeClip?.source}>
          {inGap ? "—" : clipDisplayName(activeClip, "video")}
        </span>
        <span className="source-preview__duration">
          {formatTimecode(playhead)} / {formatTimecode(duration)}
        </span>
      </div>

      <div className="preview-frame preview-frame--video preview-frame--timeline">
        <div
          className={`preview-video-wrap${safeAreaGuide ? " preview-video-wrap--safe" : ""}`}
        >
          <video
            ref={videoRef}
            className={`preview-video${inGap ? " preview-video--hidden" : ""}`}
            playsInline
            preload="auto"
            muted
            onClick={onToggle}
          />
          {safeAreaGuide && <div className="preview-safe-area" aria-hidden />}
        </div>
      </div>

      <div className="preview-controls">
        <button
          type="button"
          className="preview-controls__play"
          onClick={onToggle}
          title={playPauseTitle}
          aria-label={playing ? "Pause timeline" : "Play timeline"}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <label className="preview-controls__volume">
          <span className="preview-controls__volume-label">Volume</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.02}
            value={audioMasterMuted ? 0 : audioMasterVolume}
            onChange={(e) => {
              const v = Number(e.target.value);
              setAudioMasterVolume(v);
              if (v > 0) setAudioMasterMuted(false);
            }}
            aria-label="Preview master volume"
          />
        </label>
        <button
          type="button"
          className="preview-controls__mute"
          onClick={() => setAudioMasterMuted((m) => !m)}
          aria-pressed={audioMasterMuted}
          aria-label={audioMasterMuted ? "Unmute preview" : "Mute preview"}
        >
          {audioMasterMuted ? "Unmute" : "Mute"}
        </button>
        <span className="preview-controls__hint" title={playPauseTitle}>
          {getBindingLabel("play_pause", kbOverrides)}
        </span>
      </div>
    </div>
  );
}
