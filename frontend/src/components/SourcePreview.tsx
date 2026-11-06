import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTimelineStore } from "../store/timelineStore";
import { formatDuration, formatTimecode } from "../utils/timeFormat";

export default function SourcePreview() {
  const selectedName = useTimelineStore((s) => s.selectedFootageName);
  const clips = useTimelineStore((s) => s.footageClips);

  const clip = useMemo(() => {
    if (!selectedName) return null;
    return clips.find((c) => c.name === selectedName) ?? null;
  }, [selectedName, clips]);

  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState<number | null>(null);

  const displayDuration = mediaDuration ?? clip?.duration_seconds ?? null;

  useEffect(() => {
    setPlaying(false);
    setCurrentTime(0);
    setMediaDuration(null);
    const video = videoRef.current;
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
  }, [clip?.name]);

  useEffect(() => {
    if (!clip) return;
    const video = videoRef.current;
    if (!video) return;
    video.src = clip.proxy_url;
    video.load();
  }, [clip]);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video || !clip) return;
    if (video.paused) {
      void video.play();
    } else {
      video.pause();
    }
  }, [clip]);

  const onTimeUpdate = () => {
    const video = videoRef.current;
    if (video) setCurrentTime(video.currentTime);
  };

  const onLoadedMetadata = () => {
    const video = videoRef.current;
    if (video && Number.isFinite(video.duration)) {
      setMediaDuration(video.duration);
    }
  };

  const onPlay = () => setPlaying(true);
  const onPause = () => setPlaying(false);

  const onScrub = (value: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = value;
    setCurrentTime(value);
  };

  const maxTime = displayDuration && displayDuration > 0 ? displayDuration : 0;

  if (!clip) {
    return (
      <div className="preview-empty">
        Select a clip in the media bin to preview its 540p proxy.
      </div>
    );
  }

  return (
    <div className="source-preview">
      <div className="source-preview__meta">
        <span className="source-preview__filename" title={clip.name}>
          {clip.name}
        </span>
        <span className="source-preview__duration">
          {formatDuration(displayDuration)}
        </span>
      </div>

      <div className="preview-frame preview-frame--video">
        <video
          ref={videoRef}
          className="preview-video"
          playsInline
          preload="metadata"
          onTimeUpdate={onTimeUpdate}
          onLoadedMetadata={onLoadedMetadata}
          onPlay={onPlay}
          onPause={onPause}
          onClick={togglePlay}
        />
      </div>

      <div className="preview-controls">
        <button
          type="button"
          className="preview-controls__play"
          onClick={togglePlay}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <span className="preview-controls__time">
          {formatTimecode(currentTime)} / {formatTimecode(maxTime || currentTime)}
        </span>
      </div>

      <input
        type="range"
        className="preview-scrubber"
        min={0}
        max={maxTime || 1}
        step={0.05}
        value={Math.min(currentTime, maxTime || 0)}
        disabled={maxTime <= 0}
        onChange={(e) => onScrub(Number(e.target.value))}
        aria-label="Scrub source video"
      />
    </div>
  );
}
