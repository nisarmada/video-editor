import { describe, expect, it } from "vitest";
import {
  avLinkPartnerId,
  expandSelectionWithAvLinks,
  selectionIdsForClick,
} from "./selection";
import type { TimelineV2 } from "./types";

function plannerMegaGroupTl(): TimelineV2 {
  const gid = "same-run-uuid";
  return {
    schema_version: 2,
    tracks: [
      {
        id: "v",
        type: "video",
        clips: [
          {
            id: "v1",
            source: "a.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 0,
            group_id: gid,
          },
          {
            id: "v2",
            source: "b.mp4",
            source_in: 0,
            source_out: 2,
            timeline_start: 2,
            group_id: gid,
          },
        ],
      },
      {
        id: "c",
        type: "caption",
        clips: [
          {
            id: "cap1",
            text: "Line",
            timeline_start: 0,
            source_in: 0,
            source_out: 2,
            group_id: gid,
          },
        ],
      },
    ],
    settings: { clip_linking_enabled: true },
  };
}

describe("selectionIdsForClick", () => {
  it("click one video does not select caption or siblings with shared planner group_id", () => {
    const tl = plannerMegaGroupTl();
    expect(selectionIdsForClick(tl, "v1", true)).toEqual(["v1"]);
    expect(selectionIdsForClick(tl, "cap1", true)).toEqual(["cap1"]);
  });

  it("selects AV pair when group_kind is av_link", () => {
    const tl: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "v",
          type: "video",
          clips: [
            {
              id: "vid",
              source: "a.mp4",
              source_in: 0,
              source_out: 2,
              timeline_start: 0,
              group_id: "g",
              group_kind: "av_link",
              audio_source: "detached",
            },
          ],
        },
        {
          id: "a",
          type: "audio",
          clips: [
            {
              id: "aud",
              source: "a.mp4",
              source_in: 0,
              source_out: 2,
              timeline_start: 0,
              group_id: "g",
              group_kind: "av_link",
            },
          ],
        },
      ],
    };
    expect(selectionIdsForClick(tl, "vid", true).sort()).toEqual(["aud", "vid"]);
    expect(selectionIdsForClick(tl, "vid", false)).toEqual(["vid"]);
  });

  it("legacy detached pair without group_kind still links", () => {
    const tl: TimelineV2 = {
      schema_version: 2,
      tracks: [
        {
          id: "v",
          type: "video",
          clips: [
            {
              id: "vid",
              source: "a.mp4",
              source_in: 0,
              source_out: 2,
              timeline_start: 0,
              group_id: "g",
              audio_source: "detached",
            },
          ],
        },
        {
          id: "a",
          type: "audio",
          clips: [
            {
              id: "aud",
              source: "a.mp4",
              source_in: 0,
              source_out: 2,
              timeline_start: 0,
              group_id: "g",
            },
          ],
        },
      ],
    };
    expect(avLinkPartnerId(tl, "vid")).toBe("aud");
  });
});

describe("expandSelectionWithAvLinks", () => {
  it("does not expand marquee hits across planner group", () => {
    const tl = plannerMegaGroupTl();
    expect(expandSelectionWithAvLinks(tl, ["v1", "cap1"], true).sort()).toEqual(
      ["cap1", "v1"].sort(),
    );
  });
});
