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

export type CanvasFitMode = "contain" | "cover";
export type CanvasBarFill = "black" | "blur";

/** Project output frame (preview, captions, export). */
export type ProjectCanvas = {
  width?: number;
  height?: number;
  fps?: number;
  fit?: CanvasFitMode;
  bar_fill?: CanvasBarFill;
  /** Cover crop anchor 0–1. */
  fit_position_x?: number;
  fit_position_y?: number;
};

export type TimelineSettings = {
  width?: number;
  height?: number;
  fps?: number;
  canvas?: ProjectCanvas;
  caption_style?: CaptionStyle;
  /** When true, move/trim/split/delete follow group_id-linked clips. Default true if omitted. */
  clip_linking_enabled?: boolean;
};

export type VideoAudioSource = "embedded" | "detached";

export type TimelineClip = {
  id: string;
  source?: string;
  source_in?: number;
  source_out?: number;
  /** Caption clips: wall-clock end when source span is omitted (v2 docs). */
  timeline_end?: number;
  timeline_start: number;
  created_by?: string;
  group_id?: string;
  /** When `"av_link"`, paired with one video/audio clip (separate_audio); selection/ops may follow. */
  group_kind?: "av_link";
  /** Video clips: embedded timeline audio vs split to audio track. Default embedded if omitted. */
  audio_source?: VideoAudioSource;
  speed?: number;
  volume?: number;
  zoom?: number;
  /** Seconds; export default when omitted uses legacy 20ms boundary fades (embedded) or 20ms per clip (audio track). */
  audio_fade_in?: number;
  audio_fade_out?: number;
  /** Seconds; video opacity fade in preview and export when set. */
  video_fade_in?: number;
  video_fade_out?: number;
  transition_out?: { type: "dissolve" | "crossfade"; duration: number };
  /** Per-clip override of project canvas fit (video export only). */
  canvas_fit?: CanvasFitMode;
  canvas_bar_fill?: CanvasBarFill;
  canvas_fit_x?: number;
  canvas_fit_y?: number;
  text?: string;
  caption?: string;
  style_override?: Partial<CaptionStyle>;
  cut_intent?: { start?: string; end?: string; reason?: string };
  speech_cut_quality?: Record<string, number | boolean>;
  speech_transition_tight?: boolean;
  cut_warning_flags?: string[];
};

export type TimelineTrack = {
  id: string;
  type: TrackType;
  label?: string;
  /** When true, block edits that target this track via cursor shortcuts. */
  locked?: boolean;
  /** Mute this video or audio track in the UI (export unchanged in this milestone). */
  muted?: boolean;
  /** Linear gain for preview/export mixing (default 1). */
  volume?: number;
  /** While clips overlap this track id, ease gain down to duck_gain and back. */
  duck_under_track_id?: string;
  duck_gain?: number;
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
