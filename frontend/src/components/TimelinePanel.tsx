import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  clipDisplayName,
  clipTimelineDuration,
  timelineEnd,
  trackClipClass,
} from "../timeline/duration";
import {
  MAX_PX_PER_SEC,
  MIN_PX_PER_SEC,
  useTimelineStore,
} from "../store/timelineStore";
import { formatTimecode } from "../utils/timeFormat";

const LABEL_WIDTH = 88;
const RULER_HEIGHT = 28;
const TRACK_HEIGHT = 48;

function rulerStepSeconds(pxPerSecond: number): number {
  if (pxPerSecond >= 80) return 1;
  if (pxPerSecond >= 40) return 2;
  if (pxPerSecond >= 24) return 5;
  return 10;
}

export default function TimelinePanel() {
  const timeline = useTimelineStore((s) => s.timeline);
  const loading = useTimelineStore((s) => s.timelineLoading);
  const error = useTimelineStore((s) => s.timelineError);
  const playhead = useTimelineStore((s) => s.playheadSeconds);
  const pxPerSecond = useTimelineStore((s) => s.pxPerSecond);
  const loadTimeline = useTimelineStore((s) => s.loadTimeline);
  const setPlayhead = useTimelineStore((s) => s.setPlayheadSeconds);
  const setPxPerSecond = useTimelineStore((s) => s.setPxPerSecond);
  const planName = useTimelineStore((s) => s.planName);

  const rulerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadTimeline();
  }, [loadTimeline]);

  const duration = useMemo(
    () => (timeline ? timelineEnd(timeline) : 0),
    [timeline],
  );

  const contentWidth = Math.max(duration * pxPerSecond, 400);
  const totalWidth = LABEL_WIDTH + contentWidth;

  const ticks = useMemo(() => {
    const step = rulerStepSeconds(pxPerSecond);
    const max = Math.max(duration, step);
    const list: number[] = [];
    for (let t = 0; t <= max + 0.001; t += step) {
      list.push(t);
    }
    return list;
  }, [duration, pxPerSecond]);

  const onRulerClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const el = rulerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const t = x / pxPerSecond;
      setPlayhead(Math.min(Math.max(0, t), duration || t));
    },
    [pxPerSecond, setPlayhead, duration],
  );

  const playheadLeft = LABEL_WIDTH + playhead * pxPerSecond;

  return (
    <div className="lower-workspace">
      <div className="timeline-toolbar" aria-label="Timeline view">
        <span className="timeline-toolbar__plan">
          Timeline: {planName}.json (read-only)
        </span>
        <div className="timeline-toolbar__zoom">
          <span className="timeline-toolbar__zoom-label">Zoom</span>
          <input
            type="range"
            className="timeline-toolbar__zoom-slider"
            min={MIN_PX_PER_SEC}
            max={MAX_PX_PER_SEC}
            step={4}
            value={pxPerSecond}
            onChange={(e) => setPxPerSecond(Number(e.target.value))}
            aria-label="Timeline zoom"
          />
        </div>
        <span className="timeline-toolbar__label">
          Playhead {formatTimecode(playhead)}
          {duration > 0 ? ` · ${duration.toFixed(1)}s total` : ""}
        </span>
      </div>

      <div className="timeline-area timeline-area--loaded">
        {loading && <p className="panel-message">Loading timeline…</p>}
        {error && (
          <p className="panel-message panel-message--error">
            {error}
            <button
              type="button"
              className="link-btn"
              onClick={() => void loadTimeline()}
            >
              Retry
            </button>
          </p>
        )}
        {!loading && !error && timeline && (
          <div className="timeline-viewport">
            <div
              className="timeline-canvas"
              style={{ width: totalWidth, minHeight: "100%" }}
            >
              <div
                className="timeline-playhead"
                style={{ left: playheadLeft }}
                aria-hidden
              />

              <div className="timeline-ruler-row">
                <div
                  className="track-label track-label--sticky"
                  style={{ width: LABEL_WIDTH }}
                >
                  Time
                </div>
                <div
                  ref={rulerRef}
                  className="timeline-ruler timeline-ruler--interactive"
                  style={{ width: contentWidth, height: RULER_HEIGHT }}
                  onClick={onRulerClick}
                  role="slider"
                  aria-valuenow={playhead}
                  aria-valuemin={0}
                  aria-valuemax={duration}
                  aria-label="Timeline ruler"
                >
                  {ticks.map((t) => (
                    <span
                      key={t}
                      className="timeline-ruler__tick"
                      style={{ left: t * pxPerSecond }}
                    >
                      {t}s
                    </span>
                  ))}
                </div>
              </div>

              {timeline.tracks.map((track) => (
                <div className="track-row" key={track.id}>
                  <div
                    className="track-label track-label--sticky"
                    style={{ width: LABEL_WIDTH }}
                  >
                    {track.label ?? track.type}
                  </div>
                  <div
                    className="track-lane track-lane--timeline"
                    style={{ width: contentWidth, height: TRACK_HEIGHT }}
                  >
                    {(track.clips ?? []).map((clip) => {
                      const start = clip.timeline_start;
                      const dur = clipTimelineDuration(clip, track.type);
                      const left = start * pxPerSecond;
                      const width = Math.max(dur * pxPerSecond, 4);
                      return (
                        <div
                          key={clip.id}
                          className={trackClipClass(track.type)}
                          style={{ left, width }}
                          title={clipDisplayName(clip, track.type)}
                        >
                          {clipDisplayName(clip, track.type)}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
