import { useEffect, useMemo, useState } from "react";
import CaptionsPanel from "./CaptionsPanel";
import { clipTimelineDuration } from "../timeline/duration";
import type { TimelineClip, TimelineTrack, TimelineV2 } from "../timeline/types";
import { useTimelineStore } from "../store/timelineStore";

function findClip(
  timeline: TimelineV2,
  clipId: string,
): { track: TimelineTrack; clip: TimelineClip } | null {
  for (const track of timeline.tracks ?? []) {
    for (const clip of track.clips ?? []) {
      if (clip.id === clipId) {
        return { track, clip };
      }
    }
  }
  return null;
}

function dash<T>(v: T | undefined | null): string {
  if (v === undefined || v === null || v === "") return "—";
  return String(v);
}

const MIN_SPEED = 0.1;
const MAX_SPEED = 10;
const MIN_VOLUME = 0;
const MAX_VOLUME = 4;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;

/**
 * scripts/media.py: TimelinePiece / render_timeline use speed, volume, zoom (video only).
 * Caption burn uses transcript words remapped onto flattened *video* segments; segment
 * overlay string for each segment comes from each video clip's `caption`, or `text` if
 * no caption (timeline_format.flatten_v2_to_v1_segments). Caption-track clip `text` is
 * plan metadata only here — keep it read-only; edit video `text` / `caption` instead.
 */
export default function ClipDetails() {
  const [detailTab, setDetailTab] = useState<"details" | "captions">("details");
  const timeline = useTimelineStore((s) => s.timeline);
  const selectedClipId = useTimelineStore((s) => s.selectedClipId);
  const currentPlanName = useTimelineStore((s) => s.currentPlanName);
  const applyOperation = useTimelineStore((s) => s.applyOperation);
  const applyInProgress = useTimelineStore((s) => s.applyOperationInProgress);

  const [error, setError] = useState<string | null>(null);

  const resolved = useMemo(() => {
    if (!timeline || !selectedClipId) return null;
    return findClip(timeline, selectedClipId);
  }, [timeline, selectedClipId]);

  const clip = resolved?.clip;
  const track = resolved?.track;
  const trackType = track?.type ?? "video";

  const [speedIn, setSpeedIn] = useState("");
  const [volIn, setVolIn] = useState("");
  const [zoomIn, setZoomIn] = useState("");
  const [textIn, setTextIn] = useState("");
  const [captionIn, setCaptionIn] = useState("");
  useEffect(() => {
    setError(null);
    if (!clip) {
      setSpeedIn("");
      setVolIn("");
      setZoomIn("");
      setTextIn("");
      setCaptionIn("");
      return;
    }
    setSpeedIn(
      clip.speed !== undefined && clip.speed !== null
        ? String(clip.speed)
        : "",
    );
    setVolIn(
      clip.volume !== undefined && clip.volume !== null
        ? String(clip.volume)
        : "",
    );
    setZoomIn(
      clip.zoom !== undefined && clip.zoom !== null ? String(clip.zoom) : "",
    );
    setTextIn(clip.text ?? "");
    setCaptionIn(clip.caption ?? "");
  }, [
    clip?.id,
    clip?.speed,
    clip?.volume,
    clip?.zoom,
    clip?.text,
    clip?.caption,
  ]);

  const duration = clip && track ? clipTimelineDuration(clip, trackType) : 0;

  const isVideoTrack = trackType === "video" && clip != null;
  async function applyProps(properties: Record<string, unknown>) {
    if (!clip) return;
    setError(null);
    try {
      await applyOperation({
        operation: "set_clip_property",
        arguments: { clip_id: clip.id, properties },
      });
    } catch {
      /* store sets opErrorMessage */
    }
  }

  async function submitVideoRenderAndCaption() {
    if (!clip || !isVideoTrack) return;

    const props: Record<string, unknown> = {};

    const sp = speedIn.trim();
    if (sp === "") {
      props.speed = null;
    } else {
      const n = Number(sp);
      if (Number.isNaN(n) || n < MIN_SPEED || n > MAX_SPEED) {
        setError(`Speed must be between ${MIN_SPEED} and ${MAX_SPEED}.`);
        return;
      }
      props.speed = n;
    }

    const vol = volIn.trim();
    if (vol === "") {
      props.volume = null;
    } else {
      const n = Number(vol);
      if (Number.isNaN(n) || n < MIN_VOLUME || n > MAX_VOLUME) {
        setError(`Volume must be between ${MIN_VOLUME} and ${MAX_VOLUME}.`);
        return;
      }
      props.volume = n;
    }

    const zm = zoomIn.trim();
    if (zm === "") {
      props.zoom = null;
    } else {
      const n = Number(zm);
      if (Number.isNaN(n) || n < MIN_ZOOM || n > MAX_ZOOM) {
        setError(`Zoom must be between ${MIN_ZOOM} and ${MAX_ZOOM} (1 = none).`);
        return;
      }
      props.zoom = n;
    }

    const tx = textIn.trim();
    if (tx === "") {
      props.text = null;
    } else {
      props.text = tx;
    }

    const cap = captionIn.trim();
    if (cap === "") {
      props.caption = null;
    } else {
      props.caption = cap;
    }

    await applyProps(props);
  }

  if (!timeline) {
    return <p className="panel-message">No timeline loaded.</p>;
  }

  const planSummary =
    !selectedClipId || !resolved || !clip || !track ? (
      <div className="props-grid">
        <p className="panel-message">Plan (no clip selected)</p>
        <div className="props-row">
          <label>Name</label>
          <span>{dash(currentPlanName)}</span>
        </div>
        <div className="props-row">
          <label>Brief</label>
          <span>{dash(timeline.brief)}</span>
        </div>
        <div className="props-row">
          <label>Target length (s)</label>
          <span>
            {timeline.target_length_seconds != null
              ? String(timeline.target_length_seconds)
              : "—"}
          </span>
        </div>
      </div>
    ) : null;

  return (
    <div className="clip-details">
      <div
        className="detail-tab-bar"
        role="tablist"
        aria-label="Details panel"
      >
        <button
          type="button"
          role="tab"
          aria-selected={detailTab === "details"}
          className={`detail-tab${detailTab === "details" ? " detail-tab--active" : ""}`}
          onClick={() => setDetailTab("details")}
        >
          Details
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={detailTab === "captions"}
          className={`detail-tab${detailTab === "captions" ? " detail-tab--active" : ""}`}
          onClick={() => setDetailTab("captions")}
        >
          Captions
        </button>
      </div>

      {detailTab === "captions" && <CaptionsPanel />}

      {detailTab === "details" && planSummary}

      {detailTab === "details" && selectedClipId && resolved && clip && track ? (
        <div className="props-grid">
      <div className="props-row">
        <label>Clip id</label>
        <span title={clip.id}>{clip.id}</span>
      </div>
      <div className="props-row">
        <label>Track</label>
        <span>
          {dash(track.label)} ({dash(track.type)})
        </span>
      </div>
      <div className="props-row">
        <label>Source</label>
        <span>{dash(clip.source)}</span>
      </div>
      <div className="props-row">
        <label>source_in</label>
        <span>{dash(clip.source_in)}</span>
      </div>
      <div className="props-row">
        <label>source_out</label>
        <span>{dash(clip.source_out)}</span>
      </div>
      <div className="props-row">
        <label>timeline_start</label>
        <span>{dash(clip.timeline_start)}</span>
      </div>
      <div className="props-row">
        <label>Duration (derived)</label>
        <span>{duration.toFixed(3)}s</span>
      </div>
      <div className="props-row">
        <label>created_by</label>
        <span>{dash(clip.created_by)}</span>
      </div>
      <div className="props-row">
        <label>group_id</label>
        <span>{dash(clip.group_id)}</span>
      </div>
      <div className="props-row">
        <label>speed</label>
        {isVideoTrack ? (
          <input
            type="text"
            inputMode="decimal"
            value={speedIn}
            onChange={(e) => setSpeedIn(e.target.value)}
            disabled={applyInProgress}
          />
        ) : (
          <span>{dash(clip.speed)}</span>
        )}
      </div>
      <div className="props-row">
        <label>volume</label>
        {isVideoTrack ? (
          <input
            type="text"
            inputMode="decimal"
            value={volIn}
            onChange={(e) => setVolIn(e.target.value)}
            disabled={applyInProgress}
          />
        ) : (
          <span>{dash(clip.volume)}</span>
        )}
      </div>
      <div className="props-row">
        <label>zoom</label>
        {isVideoTrack ? (
          <input
            type="text"
            inputMode="decimal"
            value={zoomIn}
            onChange={(e) => setZoomIn(e.target.value)}
            disabled={applyInProgress}
          />
        ) : (
          <span>{dash(clip.zoom)}</span>
        )}
      </div>
      <div className="props-row">
        <label>text</label>
        {isVideoTrack ? (
          <textarea
            value={textIn}
            onChange={(e) => setTextIn(e.target.value)}
            disabled={applyInProgress}
            rows={2}
            style={{ minWidth: "100%", boxSizing: "border-box" }}
          />
        ) : (
          <span>{dash(clip.text)}</span>
        )}
      </div>
      <div className="props-row">
        <label>caption</label>
        {isVideoTrack ? (
          <textarea
            value={captionIn}
            onChange={(e) => setCaptionIn(e.target.value)}
            disabled={applyInProgress}
            rows={3}
            style={{ minWidth: "100%", boxSizing: "border-box" }}
          />
        ) : (
          <span>{dash(clip.caption)}</span>
        )}
      </div>
      {isVideoTrack && (
        <div className="props-row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={applyInProgress}
            onClick={() => void submitVideoRenderAndCaption()}
          >
            Apply speed / volume / zoom / text / caption
          </button>
        </div>
      )}
          {error && (
            <p className="panel-message panel-message--error" role="alert">
              {error}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
