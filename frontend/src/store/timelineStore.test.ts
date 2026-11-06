import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TimelineV2 } from "../timeline/types";
import { useTimelineStore } from "./timelineStore";

function twoClipTimeline(): TimelineV2 {
  return {
    schema_version: 2,
    tracks: [
      {
        id: "track-video-main",
        type: "video",
        clips: [
          {
            id: "c1",
            source: "footage/a.mp4",
            source_in: 0,
            source_out: 4,
            timeline_start: 0,
            created_by: "user",
          },
          {
            id: "c2",
            source: "footage/b.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 4,
            created_by: "user",
          },
        ],
      },
      { id: "track-audio-main", type: "audio", clips: [] },
      { id: "track-caption-main", type: "caption", clips: [] },
    ],
  };
}

function oneClipAfterDelete(): TimelineV2 {
  const tl = twoClipTimeline();
  tl.tracks[0].clips = [tl.tracks[0].clips![1]];
  return tl;
}

function splitC1Timeline(): TimelineV2 {
  const tl = twoClipTimeline();
  /** Split at timeline 1s: source 0-1 + 1-4 */
  tl.tracks[0].clips = [
    {
      id: "c1",
      source: "footage/a.mp4",
      source_in: 0,
      source_out: 1,
      timeline_start: 0,
      created_by: "user",
    },
    {
      id: "c1-right",
      source: "footage/a.mp4",
      source_in: 1,
      source_out: 4,
      timeline_start: 1,
      created_by: "user",
    },
    tl.tracks[0].clips![1],
  ];
  return tl;
}

describe("timeline undo/redo", () => {
  const origFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = origFetch;
  });

  beforeEach(() => {
    vi.restoreAllMocks();
    useTimelineStore.setState({
      currentPlanName: "draft1_v2",
      timeline: twoClipTimeline(),
      undoStack: [],
      redoStack: [],
      selectedClipId: null,
      playheadSeconds: 0.5,
      applyOperationInProgress: false,
      dragInProgress: false,
      opErrorMessage: null,
      isDirty: false,
      saveStatus: "idle",
      saveError: null,
      renderStatus: "idle",
      renderError: null,
      outputName: null,
      outputDownloadUrl: null,
      plannerRunning: false,
      plannerError: null,
      captionPreviewClipOnly: false,
      captionSafeAreaGuide: false,
    });
  });

  it("delete, undo, redo, undo, split, undo", async () => {
    const delUndo = {
      op: "add_clip",
      track_id: "track-video-main",
      clip: twoClipTimeline().tracks[0].clips![0],
    };
    const afterDel = oneClipAfterDelete();
    const mergeUndo = {
      op: "split_clip",
      clip_id: "c1",
      at_timeline_time: 1,
    };
    const afterSplit = splitC1Timeline();

    const fetchMock = vi
      .fn()
      // delete c1
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          timeline: afterDel,
          undo: delUndo,
        }),
      })
      // undo delete
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          timeline: twoClipTimeline(),
          undo: { op: "delete_clip", clip_id: "c1" },
        }),
      })
      // redo delete
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          timeline: afterDel,
          undo: delUndo,
        }),
      })
      // undo delete again
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          timeline: twoClipTimeline(),
          undo: { op: "delete_clip", clip_id: "c1" },
        }),
      })
      // split at playhead
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          timeline: afterSplit,
          undo: mergeUndo,
        }),
      })
      // undo split (merge)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          timeline: twoClipTimeline(),
          undo: { op: "split_clip", clip_id: "c1", at_timeline_time: 1 },
        }),
      });

    globalThis.fetch = fetchMock as unknown as typeof fetch;

    useTimelineStore.setState({ selectedClipId: "c1" });
    await useTimelineStore.getState().deleteSelectedClip();
    expect(useTimelineStore.getState().timeline?.tracks[0].clips).toHaveLength(
      1,
    );
    expect(useTimelineStore.getState().undoStack).toHaveLength(1);

    await useTimelineStore.getState().undo();
    expect(useTimelineStore.getState().timeline?.tracks[0].clips).toHaveLength(
      2,
    );
    expect(useTimelineStore.getState().redoStack).toHaveLength(1);

    await useTimelineStore.getState().redo();
    expect(useTimelineStore.getState().timeline?.tracks[0].clips).toHaveLength(
      1,
    );

    await useTimelineStore.getState().undo();
    expect(useTimelineStore.getState().timeline?.tracks[0].clips).toHaveLength(
      2,
    );

    useTimelineStore.setState({ selectedClipId: "c1", playheadSeconds: 1.0 });
    await useTimelineStore.getState().splitAtPlayhead();
    expect(useTimelineStore.getState().timeline?.tracks[0].clips?.length).toBe(
      3,
    );

    await useTimelineStore.getState().undo();
    expect(useTimelineStore.getState().timeline?.tracks[0].clips).toHaveLength(
      2,
    );

    expect(fetchMock.mock.calls.length).toBe(6);
  });
});
