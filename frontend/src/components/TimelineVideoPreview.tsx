import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTimelineAudio } from "../audio/useTimelineAudio";
import { useTimelinePlaybackClock } from "../hooks/useTimelinePlaybackClock";
import { requestFootageAnalyze } from "../api/planner";
import {
  activeVideoClipAt,
  clipDisplayName,
  getSortedVideoClips,
  proxyUrlFromSource,
  timelineEnd,
  timelineToSourceSeconds,
} from "../timeline/duration";
import { useCaptionPreviewOverlay } from "../hooks/useCaptionPreviewOverlay";
import { useTimelineStore } from "../store/timelineStore";
import { previewPunchInScale } from "../timeline/exportZoomPreview";
import { videoFadeOpacityAt } from "../timeline/previewFades";
import { formatTimecode } from "../utils/timeFormat";
import { useKeybindingsStore } from "../store/keybindingsStore";
import { useEditorSettingsStore } from "../store/editorSettingsStore";
import { getBindingLabel, getBindingTitle } from "../shortcuts/tooltip";

function footageBasename(source: string | undefined): string {
  if (!source) return "clip";
  const parts = source.split("/");
  return parts[parts.length - 1] ?? source;
}

export default function TimelineVideoPreview() {
  useEditorSettingsStore((s) => s.shortcutTargeting);
  useEditorSettingsStore((s) => s.perActionTargetMode);
  useTimelinePlaybackClock();

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
  const [proxyErrorSource, setProxyErrorSource] = useState<string | null>(
    null,
  );
  const [proxyRegenBusy, setProxyRegenBusy] = useState(false);

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

  // Follow master playhead: load proxy, seek, play/pause (never advance playhead here).
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

    if (proxyErrorSource && activeClip.source !== proxyErrorSource) {
      setProxyErrorSource(null);
    }

    const wantTime = timelineToSourceSeconds(activeClip, playhead);
    const srcIn = activeClip.source_in ?? 0;
    const srcOut = activeClip.source_out ?? srcIn;
    const clamped = Math.min(
      Math.max(wantTime, srcIn),
      Math.max(srcOut - 1e-3, srcIn),
    );

    const speed = activeClip.speed && activeClip.speed > 0 ? activeClip.speed : 1;
    video.playbackRate = speed;

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
        if (playing && !proxyErrorSource) {
          void video.play().catch(() => {});
        }
      };
      video.addEventListener("loadedmetadata", onReady);
    } else {
      if (!playing || clipChanged) {
        doSeek();
      }
      if (playing && !proxyErrorSource) {
        void video.play().catch(() => {});
      } else if (!playing) {
        video.pause();
      }
    }
  }, [
    timeline,
    clipId,
    proxyUrl,
    playing,
    playhead,
    activeClip,
    proxyErrorSource,
  ]);

  // Soft drift resync when video is playing (clock remains master).
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !playing || !activeClip) return;

    const iv = window.setInterval(() => {
      if (!useTimelineStore.getState().timelinePlaying) return;
      const ph = useTimelineStore.getState().playheadSeconds;
      const clip = activeVideoClipAt(clipsRef.current, ph);
      if (!clip || clip.id !== activeClip.id) return;
      const want = timelineToSourceSeconds(clip, ph);
      if (Math.abs(video.currentTime - want) > 0.25) {
        video.currentTime = want;
      }
    }, 400);
    return () => clearInterval(iv);
  }, [playing, activeClip?.id]);

  const onVideoError = useCallback(() => {
    if (activeClip?.source) {
      setProxyErrorSource(activeClip.source);
    }
  }, [activeClip?.source]);

  const regenerateProxy = useCallback(async () => {
    const name = footageBasename(proxyErrorSource ?? activeClip?.source);
    if (!name) return;
    setProxyRegenBusy(true);
    try {
      await requestFootageAnalyze({ names: [name] });
      setProxyErrorSource(null);
      useTimelineStore.getState().setShortcutToast(`Queued proxy for ${name}`);
    } catch (e) {
      useTimelineStore.getState().setUiBannerError(
        e instanceof Error ? e.message : "Could not queue proxy",
      );
    } finally {
      setProxyRegenBusy(false);
    }
  }, [proxyErrorSource, activeClip?.source]);

  const kbOverrides = useKeybindingsStore((s) => s.overrides);
  const playPauseTitle = getBindingTitle("play_pause", kbOverrides);
  const onToggle = () => togglePlaying();

  if (!timeline) {
    return (
      <div className="preview-empty">Load a timeline to preview playback.</div>
    );
  }

  const inGap = !activeClip;
  const punchScale = previewPunchInScale(activeClip?.zoom);
  const videoOpacity =
    activeClip && !inGap
      ? videoFadeOpacityAt(activeClip, playhead)
      : 1;

  const showProxyError =
    proxyErrorSource &&
    activeClip?.source === proxyErrorSource;

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

      {showProxyError && (
        <p className="panel-message panel-message--error" role="alert">
          Proxy not available for {footageBasename(proxyErrorSource)}.{" "}
          <button
            type="button"
            className="btn"
            disabled={proxyRegenBusy}
            onClick={() => void regenerateProxy()}
          >
            {proxyRegenBusy ? "Queueing…" : "Regenerate"}
          </button>
        </p>
      )}

      <div className="preview-frame preview-frame--video preview-frame--timeline">
        <div
          className={
            `preview-video-wrap${safeAreaGuide ? " preview-video-wrap--safe" : ""}` +
            (punchScale > 1 ? " preview-video-wrap--punch" : "")
          }
        >
          <video
            ref={videoRef}
            className={`preview-video${inGap || showProxyError ? " preview-video--hidden" : ""}`}
            playsInline
            preload="auto"
            muted
            onClick={onToggle}
            onError={onVideoError}
            style={{
              ...(punchScale > 1
                ? {
                    transform: `scale(${punchScale})`,
                    transformOrigin: "center center",
                  }
                : {}),
              opacity: videoOpacity < 0.999 ? videoOpacity : undefined,
            }}
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
