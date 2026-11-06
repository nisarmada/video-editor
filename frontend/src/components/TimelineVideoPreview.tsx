import { useEffect, useMemo, useRef } from "react";
import {
  activeVideoClipAt,
  clipTimelineDuration,
  clipDisplayName,
  getSortedVideoClips,
  proxyUrlFromSource,
  timelineEnd,
  timelineToSourceSeconds,
} from "../timeline/duration";
import { useTimelineStore } from "../store/timelineStore";
import { formatTimecode } from "../utils/timeFormat";

const SOURCE_END_EPS = 0.05;

export default function TimelineVideoPreview() {
  const timeline = useTimelineStore((s) => s.timeline);
  const playhead = useTimelineStore((s) => s.playheadSeconds);
  const playing = useTimelineStore((s) => s.timelinePlaying);
  const setPlaying = useTimelineStore((s) => s.setTimelinePlaying);
  const togglePlaying = useTimelineStore((s) => s.toggleTimelinePlaying);

  const videoRef = useRef<HTMLVideoElement>(null);
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

    const doSeek = () => {
      if (Math.abs(video.currentTime - clamped) > 0.04) {
        video.currentTime = clamped;
      }
    };

    if (playing && !needNewSrc) {
      return;
    }

    if (needNewSrc) {
      video.src = proxyUrl;
      video.load();
      const onReady = () => {
        video.removeEventListener("loadedmetadata", onReady);
        doSeek();
        if (playing) void video.play().catch(() => setPlaying(false));
      };
      video.addEventListener("loadedmetadata", onReady);
    } else {
      doSeek();
    }
  }, [timeline, clipId, proxyUrl, playing, playhead, activeClip, setPlaying]);

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
        if (video && video.paused) {
          void video.play().catch(() => setPlaying(false));
        }
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
  }, [playing, timeline, setPlaying]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.tagName === "BUTTON" ||
          t.isContentEditable)
      ) {
        return;
      }
      e.preventDefault();
      togglePlaying();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePlaying]);

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
        <video
          ref={videoRef}
          className={`preview-video${inGap ? " preview-video--hidden" : ""}`}
          playsInline
          preload="auto"
          muted
          onClick={onToggle}
        />
      </div>

      <div className="preview-controls">
        <button
          type="button"
          className="preview-controls__play"
          onClick={onToggle}
          aria-label={playing ? "Pause timeline" : "Play timeline"}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <span className="preview-controls__hint">Space — video track</span>
      </div>
    </div>
  );
}
