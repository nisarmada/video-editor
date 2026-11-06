export type TrackType = "video" | "audio" | "caption";

/** Caption burn-in style (plan `settings.caption_style` + optional per-clip `style_override`). */
export type CaptionAnimation =
  | "none"
  | "word_highlight"
  | "word_pop"
  | "word_box"
  | "karaoke_sweep"
  | "typewriter"
  | "bounce_in"
  | "fade_in"
  | "neon";

export type CaptionStyle = {
  preset?: string;
  font_family?: string;
  /** Fraction of video height, e.g. 0.04 */
  font_size?: number;
  bold?: boolean;
  italic?: boolean;
  uppercase?: boolean;
  text_color?: string;
  active_word_color?: string;
  outline_color?: string;
  outline_width?: number;
  shadow_color?: string;
  shadow_offset?: [number, number];
  box_color?: string;
  box_opacity?: number;
  box_padding?: number;
  /** Percent from top (0–100) */
  position_y?: number;
  max_words_per_line?: number;
  max_lines?: number;
  line_spacing?: number;
  animation?: CaptionAnimation;
  animation_intensity?: number;
  active_word_scale?: number;
};

/** Optional project output defaults; render still uses fixed 1080×1920 @ 30 until wired. */
export type TimelineSettings = {
  width?: number;
  height?: number;
  fps?: number;
  caption_style?: CaptionStyle;
};

export type TimelineClip = {
  id: string;
  source?: string;
  source_in?: number;
  source_out?: number;
  timeline_start: number;
  created_by?: string;
  group_id?: string;
  speed?: number;
  volume?: number;
  zoom?: number;
  text?: string;
  caption?: string;
  style_override?: Partial<CaptionStyle>;
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
  settings?: TimelineSettings;
  tracks: TimelineTrack[];
};
