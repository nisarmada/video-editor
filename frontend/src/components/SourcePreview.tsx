import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTimelineStore } from "../store/timelineStore";
import { fetchMediaCatalog } from "../api/catalog";
import { requestFootageRetranscribe, requestFrameCaptions } from "../api/footage";
import SourceTakesPanel from "./SourceTakesPanel";
import { formatDuration, formatTimecode } from "../utils/timeFormat";

export default function SourcePreview() {
  const selectedName = useTimelineStore((s) => s.selectedFootageName);
  const clips = useTimelineStore((s) => s.footageClips);
  const sourcePlaybackRequest = useTimelineStore((s) => s.sourcePlaybackRequest);

  const clip = useMemo(() => {
    if (!selectedName) return null;
    return clips.find((c) => c.name === selectedName) ?? null;
  }, [selectedName, clips]);

  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState<number | null>(null);
  const [retranscribeBusy, setRetranscribeBusy] = useState(false);
  const [retranscribeMsg, setRetranscribeMsg] = useState<string | null>(null);
  const [captionsBusy, setCaptionsBusy] = useState(false);
  const [captionsStatus, setCaptionsStatus] = useState<string | null>(null);
  const fetchFootage = useTimelineStore((s) => s.fetchFootage);

  const displayDuration = mediaDuration ?? clip?.duration_seconds ?? null;

  useEffect(() => {
    if (!clip?.name || clip.kind === "audio") {
      setCaptionsStatus(null);
      return;
    }
    let cancelled = false;
    void fetchMediaCatalog({ names: [clip.name] })
      .then(({ entries }) => {
        if (cancelled) return;
        const row = entries[0];
        setCaptionsStatus(row?.analysis?.ai_frame_captions ?? null);
      })
      .catch(() => {
        if (!cancelled) setCaptionsStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, [clip?.name, clip?.kind]);

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

  useEffect(() => {
    if (!sourcePlaybackRequest || !clip) return;
    const video = videoRef.current;
    if (!video) return;
    const { start, end } = sourcePlaybackRequest;
    const playRange = () => {
      video.currentTime = Math.max(0, start);
      void video.play();
    };
    if (video.readyState >= 1) {
      playRange();
    } else {
      video.addEventListener("loadedmetadata", playRange, { once: true });
    }
    const onTime = () => {
      if (video.currentTime >= end) {
        video.pause();
        video.currentTime = start;
      }
    };
    video.addEventListener("timeupdate", onTime);
    return () => video.removeEventListener("timeupdate", onTime);
  }, [sourcePlaybackRequest, clip]);

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
        {clip.kind !== "audio" && captionsStatus === "not analyzed" && (
          <button
            type="button"
            className="btn btn--ghost source-preview__retranscribe"
            disabled={captionsBusy}
            title="Run paid Haiku frame captions (uses cached keyframes when present)"
            onClick={() => {
              setCaptionsBusy(true);
              setRetranscribeMsg(null);
              void requestFrameCaptions(clip.name)
                .then(() => {
                  setRetranscribeMsg("Queued frame captions.");
                  void fetchFootage({ silent: true });
                })
                .catch((e: unknown) => {
                  setRetranscribeMsg(
                    e instanceof Error ? e.message : "Frame captions failed",
                  );
                })
                .finally(() => setCaptionsBusy(false));
            }}
          >
            {captionsBusy ? "Queuing…" : "Generate captions"}
          </button>
        )}
        {(clip.has_audio ?? true) && (
          <button
            type="button"
            className="btn btn--ghost source-preview__retranscribe"
            disabled={retranscribeBusy}
            title="Re-run Whisper with current transcription settings (keeps word timestamps)"
            onClick={() => {
              if (
                !window.confirm(
                  `Re-transcribe "${clip.name}"? This rebuilds transcript, silences, audio metrics, takes, and embeddings.`,
                )
              ) {
                return;
              }
              setRetranscribeBusy(true);
              setRetranscribeMsg(null);
              void requestFootageRetranscribe(clip.name)
                .then(() => {
                  setRetranscribeMsg("Queued re-transcription.");
                  void fetchFootage({ silent: true });
                })
                .catch((e: unknown) => {
                  setRetranscribeMsg(
                    e instanceof Error ? e.message : "Re-transcribe failed",
                  );
                })
                .finally(() => setRetranscribeBusy(false));
            }}
          >
            {retranscribeBusy ? "Queuing…" : "Re-transcribe"}
          </button>
        )}
      </div>
      {retranscribeMsg && (
        <p className="panel-message" role="status">
          {retranscribeMsg}
        </p>
      )}

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
      <SourceTakesPanel />
    </div>
  );
}
