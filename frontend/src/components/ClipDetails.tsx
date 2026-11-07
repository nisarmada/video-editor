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
  const selectedClipIds = useTimelineStore((s) => s.selectedClipIds);
  const currentPlanName = useTimelineStore((s) => s.currentPlanName);
  const applyOperation = useTimelineStore((s) => s.applyOperation);
  const applyInProgress = useTimelineStore((s) => s.applyOperationInProgress);

  const [error, setError] = useState<string | null>(null);

  const multi = selectedClipIds.length > 1;

  const resolved = useMemo(() => {
    if (!timeline || !selectedClipId || multi) return null;
    return findClip(timeline, selectedClipId);
  }, [timeline, selectedClipId, multi]);

  const clip = resolved?.clip;
  const track = resolved?.track;
  const trackType = track?.type ?? "video";

  const [speedIn, setSpeedIn] = useState("");
  const [volIn, setVolIn] = useState("");
  const [zoomIn, setZoomIn] = useState("");
  const [textIn, setTextIn] = useState("");
  const [captionIn, setCaptionIn] = useState("");
  const [audioFadeInIn, setAudioFadeInIn] = useState("");
  const [audioFadeOutIn, setAudioFadeOutIn] = useState("");
  const [videoFadeInIn, setVideoFadeInIn] = useState("");
  const [videoFadeOutIn, setVideoFadeOutIn] = useState("");
  const [transitionDurIn, setTransitionDurIn] = useState("");
  const [duckUnderIn, setDuckUnderIn] = useState("");
  const [duckGainIn, setDuckGainIn] = useState("");
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
    setAudioFadeInIn(
      clip.audio_fade_in != null ? String(clip.audio_fade_in) : "",
    );
    setAudioFadeOutIn(
      clip.audio_fade_out != null ? String(clip.audio_fade_out) : "",
    );
    setVideoFadeInIn(
      clip.video_fade_in != null ? String(clip.video_fade_in) : "",
    );
    setVideoFadeOutIn(
      clip.video_fade_out != null ? String(clip.video_fade_out) : "",
    );
    setTransitionDurIn(
      clip.transition_out?.duration != null
        ? String(clip.transition_out.duration)
        : "",
    );
    setDuckUnderIn(track?.duck_under_track_id ?? "");
    setDuckGainIn(
      track?.duck_gain != null ? String(track.duck_gain) : "",
    );
  }, [
    clip?.id,
    clip?.speed,
    clip?.volume,
    clip?.zoom,
    clip?.text,
    clip?.caption,
    clip?.audio_fade_in,
    clip?.audio_fade_out,
    clip?.video_fade_in,
    clip?.video_fade_out,
    clip?.transition_out,
    track?.duck_under_track_id,
    track?.duck_gain,
  ]);

  const duration = clip && track ? clipTimelineDuration(clip, trackType) : 0;

  const isVideoTrack = trackType === "video" && clip != null;
  const setClipPropertyBatch = useTimelineStore((s) => s.setClipPropertyBatch);

  async function applyProps(properties: Record<string, unknown>) {
    setError(null);
    try {
      if (multi) {
        await setClipPropertyBatch(selectedClipIds, properties);
        return;
      }
      if (!clip) return;
      await applyOperation({
        operation: "set_clip_property",
        arguments: { clip_id: clip.id, properties },
      });
    } catch {
      /* store sets opErrorMessage */
    }
  }

  const multiAllCaption = useMemo(() => {
    if (!timeline || !multi) return false;
    return selectedClipIds.every((id) => {
      const r = findClip(timeline, id);
      return r?.track.type === "caption";
    });
  }, [timeline, multi, selectedClipIds]);

  const mixedSpeed = useMemo(() => {
    if (!timeline || !multi) return false;
    const vals = new Set(
      selectedClipIds.map((id) => {
        const r = findClip(timeline, id);
        return r?.clip.speed ?? 1;
      }),
    );
    return vals.size > 1;
  }, [timeline, multi, selectedClipIds]);

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

    const parseOpt = (s: string, key: string) => {
      if (s.trim() === "") return { [key]: null };
      const n = Number(s);
      if (!Number.isFinite(n) || n < 0) {
        setError(`${key} must be a non-negative number.`);
        throw new Error("bad");
      }
      return { [key]: n };
    };

    try {
      Object.assign(props, parseOpt(audioFadeInIn, "audio_fade_in"));
      Object.assign(props, parseOpt(audioFadeOutIn, "audio_fade_out"));
      if (isVideoTrack) {
        Object.assign(props, parseOpt(videoFadeInIn, "video_fade_in"));
        Object.assign(props, parseOpt(videoFadeOutIn, "video_fade_out"));
        const td = transitionDurIn.trim();
        if (td === "") {
          props.transition_out = null;
        } else {
          const n = Number(td);
          if (!Number.isFinite(n) || n <= 0) {
            setError("Transition duration must be > 0.");
            return;
          }
          props.transition_out = { type: "dissolve", duration: n };
        }
      }
    } catch {
      return;
    }

    await applyProps(props);
  }

  async function submitAudioClipProps() {
    if (!clip || trackType !== "audio") return;
    const props: Record<string, unknown> = {};
    const vol = volIn.trim();
    if (vol === "") props.volume = null;
    else {
      const n = Number(vol);
      if (!Number.isFinite(n) || n < MIN_VOLUME || n > MAX_VOLUME) {
        setError(`Volume must be between ${MIN_VOLUME} and ${MAX_VOLUME}.`);
        return;
      }
      props.volume = n;
    }
    const parseOpt = (s: string, key: string) => {
      if (s.trim() === "") return { [key]: null };
      const n = Number(s);
      if (!Number.isFinite(n) || n < 0) {
        setError(`${key} must be a non-negative number.`);
        throw new Error("bad");
      }
      return { [key]: n };
    };
    try {
      Object.assign(props, parseOpt(audioFadeInIn, "audio_fade_in"));
      Object.assign(props, parseOpt(audioFadeOutIn, "audio_fade_out"));
    } catch {
      return;
    }
    await applyProps(props);
  }

  async function submitTrackDuck() {
    if (!track || trackType !== "audio") return;
    const duckProps: Record<string, unknown> = {};
    duckProps.duck_under_track_id = duckUnderIn.trim() || null;
    if (duckGainIn.trim() === "") duckProps.duck_gain = null;
    else {
      const n = Number(duckGainIn);
      if (!Number.isFinite(n) || n < 0 || n > 1) {
        setError("duck_gain must be between 0 and 1.");
        return;
      }
      duckProps.duck_gain = n;
    }
    await applyOperation({
      operation: "set_track_property",
      arguments: { track_id: track.id, properties: duckProps },
    });
  }

  if (!timeline) {
    return <p className="panel-message">No timeline loaded.</p>;
  }

  const planSummary =
    (!selectedClipId && selectedClipIds.length === 0) ||
    (!multi && (!resolved || !clip || !track)) ? (
      <div className="props-grid">
        <p className="panel-message">
          {multi ? `${selectedClipIds.length} clips selected` : "Plan (no clip selected)"}
        </p>
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

      {detailTab === "details" && multi ? (
        <div className="props-grid">
          <p className="panel-message">{selectedClipIds.length} clips selected</p>
          <div className="props-row">
            <label>speed</label>
            <input
              type="text"
              inputMode="decimal"
              placeholder={mixedSpeed ? "Mixed" : "1"}
              value={speedIn}
              onChange={(e) => setSpeedIn(e.target.value)}
              disabled={applyInProgress}
              onBlur={() => {
                const v = Number(speedIn);
                if (!Number.isFinite(v)) return;
                void applyProps({ speed: Math.min(MAX_SPEED, Math.max(MIN_SPEED, v)) });
              }}
            />
          </div>
          <div className="props-row">
            <label>volume</label>
            <input
              type="text"
              inputMode="decimal"
              placeholder="Mixed"
              value={volIn}
              onChange={(e) => setVolIn(e.target.value)}
              disabled={applyInProgress}
              onBlur={() => {
                const v = Number(volIn);
                if (!Number.isFinite(v)) return;
                void applyProps({ volume: Math.min(MAX_VOLUME, Math.max(MIN_VOLUME, v)) });
              }}
            />
          </div>
          {multiAllCaption ? (
            <div className="props-row">
              <label>text</label>
              <input
                type="text"
                placeholder="Mixed"
                value={textIn}
                onChange={(e) => setTextIn(e.target.value)}
                disabled={applyInProgress}
                onBlur={() => {
                  const t = textIn.trim();
                  if (!t) return;
                  void applyProps({ text: t });
                }}
              />
            </div>
          ) : null}
        </div>
      ) : null}

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
        {isVideoTrack || trackType === "audio" ? (
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
      {(isVideoTrack || trackType === "audio") && (
        <>
          <div className="props-row">
            <label>audio_fade_in (s)</label>
            <input
              type="text"
              inputMode="decimal"
              value={audioFadeInIn}
              onChange={(e) => setAudioFadeInIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="default"
            />
          </div>
          <div className="props-row">
            <label>audio_fade_out (s)</label>
            <input
              type="text"
              inputMode="decimal"
              value={audioFadeOutIn}
              onChange={(e) => setAudioFadeOutIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="default"
            />
          </div>
        </>
      )}
      {isVideoTrack && (
        <>
          <div className="props-row">
            <label>video_fade_in (s)</label>
            <input
              type="text"
              inputMode="decimal"
              value={videoFadeInIn}
              onChange={(e) => setVideoFadeInIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="none"
            />
          </div>
          <div className="props-row">
            <label>video_fade_out (s)</label>
            <input
              type="text"
              inputMode="decimal"
              value={videoFadeOutIn}
              onChange={(e) => setVideoFadeOutIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="none"
            />
          </div>
          <div className="props-row">
            <label>
              transition_out (s){" "}
              <span className="props-export-only">export only</span>
            </label>
            <input
              type="text"
              inputMode="decimal"
              value={transitionDurIn}
              onChange={(e) => setTransitionDurIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="dissolve duration"
            />
          </div>
        </>
      )}
      {trackType === "audio" && (
        <>
          <div className="props-row">
            <label>duck_under_track_id</label>
            <input
              type="text"
              value={duckUnderIn}
              onChange={(e) => setDuckUnderIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="audio track id"
            />
          </div>
          <div className="props-row">
            <label>duck_gain</label>
            <input
              type="text"
              inputMode="decimal"
              value={duckGainIn}
              onChange={(e) => setDuckGainIn(e.target.value)}
              disabled={applyInProgress}
              placeholder="0.25"
            />
          </div>
          <div className="props-row">
            <button
              type="button"
              className="btn"
              disabled={applyInProgress}
              onClick={() => void submitTrackDuck()}
            >
              Apply track ducking
            </button>
          </div>
        </>
      )}
      {isVideoTrack && clip ? (
        <>
          <div className="props-row">
            <label>canvas fit</label>
            <select
              value={clip.canvas_fit ?? ""}
              disabled={applyInProgress}
              onChange={(e) => {
                const v = e.target.value;
                void applyProps({
                  canvas_fit: v === "" ? null : v,
                });
              }}
            >
              <option value="">Project default</option>
              <option value="contain">Contain</option>
              <option value="cover">Cover</option>
            </select>
          </div>
          <div className="props-row">
            <label>letterbox</label>
            <select
              value={clip.canvas_bar_fill ?? ""}
              disabled={applyInProgress}
              onChange={(e) => {
                const v = e.target.value;
                void applyProps({
                  canvas_bar_fill: v === "" ? null : v,
                });
              }}
            >
              <option value="">Project default</option>
              <option value="black">Black bars</option>
              <option value="blur">Blur bars</option>
            </select>
          </div>
        </>
      ) : null}
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
            Apply clip effects
          </button>
        </div>
      )}
      {trackType === "audio" && !multi && (
        <div className="props-row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={applyInProgress}
            onClick={() => void submitAudioClipProps()}
          >
            Apply volume / audio fades
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
