import { useEffect } from "react";
import { useTimelineStore } from "../store/timelineStore";
import { timelineEnd } from "../timeline/duration";
import { advancePlayhead as tickPlayhead } from "../timeline/playbackClock";

/**
 * Single master clock: while timelinePlaying, advance playheadSeconds from rAF.
 * Video and audio hooks follow this time (never drive it).
 */
export function useTimelinePlaybackClock(): void {
  const playing = useTimelineStore((s) => s.timelinePlaying);
  const timeline = useTimelineStore((s) => s.timeline);
  const dragInProgress = useTimelineStore((s) => s.dragInProgress);

  useEffect(() => {
    if (!playing || !timeline || dragInProgress) return;

    let raf = 0;
    let last = performance.now();

    const step = (now: number) => {
      const st = useTimelineStore.getState();
      if (!st.timelinePlaying || st.dragInProgress || !st.timeline) {
        return;
      }
      const dt = (now - last) / 1000;
      last = now;
      const maxT = timelineEnd(st.timeline);
      const { time, atEnd } = tickPlayhead(st.playheadSeconds, dt, maxT);
      st.setPlayheadSeconds(time);
      if (atEnd) {
        st.setTimelinePlaying(false);
        return;
      }
      raf = requestAnimationFrame(step);
    };

    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, timeline, dragInProgress]);
}
