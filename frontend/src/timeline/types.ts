export type TrackType = "video" | "audio" | "caption";

export type TimelineClip = {
  id: string;
  source?: string;
  source_in?: number;
  source_out?: number;
  timeline_start: number;
  created_by?: string;
  group_id?: string;
  speed?: number;
  text?: string;
  caption?: string;
};

export type TimelineTrack = {
  id: string;
  type: TrackType;
  label?: string;
  clips: TimelineClip[];
};

export type TimelineV2 = {
  schema_version: 2;
  name?: string;
  brief?: string;
  target_length_seconds?: number;
  tracks: TimelineTrack[];
};
