# Timeline schema v2

CapCut-style multi-track timelines for the visual editor. **v1 plans remain supported** (flat `segments` list).

## Top-level object

| Field | Required | Description |
|-------|----------|-------------|
| `schema_version` | yes | Must be `2` |
| `name` | no | Slug or display name |
| `brief` | no | Creative brief (from AI planner) |
| `target_length_seconds` | no | Intended output length |
| `settings` | no | Global output settings (see below) |
| `tracks` | yes | Array of track objects |

### `settings` (optional)

```json
{
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "caption_style": {
    "preset": "bold_pop",
    "font_size": 0.045
  }
}
```

Defaults match the current renderer: 1080×1920 @ 30 fps. Omitting `caption_style` uses built-in **Bold Pop** (`bold_pop`).

#### `settings.caption_style` (optional)

Burn-in captions (when export has captions enabled) use `scripts/captions_ass.py` + libass. Fields are validated server-side (`scripts/caption_style.py`).

| Field | Type | Description |
|-------|------|-------------|
| `preset` | string | Built-in preset id from `backend/caption_presets/` (default `bold_pop`) |
| `font_family` | string | Logical family (Montserrat, Poppins, Inter, Oswald, Anton, Bebas Neue, Bangers, …) — must match a bundled OFL font |
| `font_size` | number | Size as **fraction of video height** (e.g. `0.04` ≈ 4% of height) |
| `bold`, `italic`, `uppercase` | bool | Typography |
| `text_color`, `active_word_color`, `outline_color`, `shadow_color`, `box_color` | `#RRGGBB` | Colors |
| `outline_width`, `box_opacity`, `box_padding` | number | Outline / box |
| `shadow_offset` | `[x, y]` | Shadow pixels |
| `position_y` | number | Vertical anchor as **percent from top** (0–100), safe margins in renderer |
| `max_words_per_line` | int | 1–5 |
| `max_lines` | int | 1–5 (chunking uses `max_words_per_line`) |
| `line_spacing` | number | Line spacing factor (reserved for multi-line) |
| `animation` | string | `none`, `word_highlight`, `word_pop`, `word_box`, `karaoke_sweep`, `typewriter`, `bounce_in`, `fade_in`, `neon` |
| `animation_intensity` | number | 0–1 |
| `active_word_scale` | number | ~1.0–1.4 for pop/bounce |

#### Per-clip `style_override` (optional, **video** clips)

Override any of the same keys as `settings.caption_style` for that clip only (merged on top of the plan style).

| Field | Tracks | Description |
|-------|--------|-------------|
| `style_override` | video | Partial `caption_style` fields |

## Tracks

Each track:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Stable track id (e.g. `track-video-main`) |
| `type` | yes | `"video"`, `"audio"`, or `"caption"` |
| `label` | no | UI label |
| `clips` | yes | Array of clips (may be empty) |

Typical layout:

1. **video** — picture cuts from `footage/` (required for render)
2. **audio** — voiceover, music, sfx (validated; mixed rendering coming later)
3. **caption** — on-screen text clips (optional; burn-in may still use transcript remap from video)

## Clip object (all tracks)

Common fields:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Stable clip id (UUID recommended) |
| `source` | video/audio: yes | Path to media file, usually `footage/...` |
| `source_in` | yes* | Start time in source file (seconds) |
| `source_out` | yes* | End time in source file (seconds) |
| `timeline_start` | yes | Where this clip starts on the timeline (seconds) |
| `created_by` | yes | `"user"` or `"ai"` |
| `group_id` | no | Link clips edited together (e.g. same “scene”) |

\* **Caption** clips use `source_in` / `source_out` optionally; they must have `text` and a duration implied by `source_out - source_in` or `timeline_end`.

### Optional fields

| Field | Tracks | Description |
|-------|--------|-------------|
| `zoom` | video | Scale factor (e.g. `1.15` punch-in). Renderer: centered crop then scale back to frame (`scripts/media.py`, `_zoom_punch_filter`) |
| `speed` | video, audio | Playback speed (`1.0` = normal). Renderer: `setpts` + `atempo` on video/audio cuts (`scripts/media.py`, `build_timeline_filter_graph`) |
| `volume` | audio, video | Linear gain (`1.0` = unity; `0` = silence). Renderer: FFmpeg `volume` on clip audio (`scripts/media.py`, `_volume_filter_expr`) |
| `text` | caption | Caption string |
| `caption` | video | Legacy-friendly short caption note (planner) |
| `style_override` | video | Optional partial caption style for burn-in |

### Clip duration on the timeline

For **video** and **audio**:

```
timeline_duration = (source_out - source_in) / speed
```

(If `speed` is omitted, use `1.0`.)

For **caption** clips, duration is `(source_out - source_in)` or explicit `timeline_end - timeline_start` when both ends are set.

## v1 compatibility

**v1** (no `schema_version`):

- A JSON **array** of segments, or an object with `"segments": [...]`
- Each segment: `{ "source", "start", "end", "caption?", "reason?", "zoom?", "transition?" }`
- Implicit timeline: segments are concatenated **in file order** (no gaps)

Convert with:

```bash
python scripts/convert_v1_to_v2.py plans/draft1.json plans/draft1_v2.json
```

## Example (v2)

```json
{
  "schema_version": 2,
  "name": "amsterdam_beers_casual",
  "brief": "30s reel, hook in first 2 seconds, casual vibe",
  "target_length_seconds": 30,
  "settings": {
    "width": 1080,
    "height": 1920,
    "fps": 30
  },
  "tracks": [
    {
      "id": "track-video-main",
      "type": "video",
      "label": "Video",
      "clips": [
        {
          "id": "a1b2c3d4-0001-4000-8000-000000000001",
          "source": "footage/8E159DE7-4F00-4034-8E14-B8AA14C9BB70.mp4",
          "source_in": 0.0,
          "source_out": 2.32,
          "timeline_start": 0.0,
          "caption": "Good day, you decided to work",
          "created_by": "ai",
          "group_id": "hook"
        },
        {
          "id": "a1b2c3d4-0002-4000-8000-000000000002",
          "source": "footage/7B11712B-ADD8-4E5E-BAC6-9567827A23CF.mp4",
          "source_in": 1.54,
          "source_out": 8.64,
          "timeline_start": 2.32,
          "zoom": 1.0,
          "speed": 1.0,
          "volume": 1.0,
          "created_by": "ai",
          "group_id": "invite"
        }
      ]
    },
    {
      "id": "track-audio-music",
      "type": "audio",
      "label": "Music",
      "clips": []
    },
    {
      "id": "track-caption-main",
      "type": "caption",
      "label": "Captions",
      "clips": [
        {
          "id": "a1b2c3d4-0003-4000-8000-000000000003",
          "source": "footage/8E159DE7-4F00-4034-8E14-B8AA14C9BB70.mp4",
          "source_in": 0.0,
          "source_out": 2.32,
          "timeline_start": 0.0,
          "text": "Good day, you decided to work",
          "created_by": "ai",
          "group_id": "hook"
        }
      ]
    }
  ]
}
```

## Validation rules (v2)

- Every clip has `id`, `timeline_start`, `created_by` (`user` | `ai`)
- Video/audio: `source`, `source_in`, `source_out`; `source_in < source_out`; min length 0.3s
- Clips on the **same track** must not overlap in timeline time
- `source` paths must exist; `source_out` within file duration
- **Render** uses the **video** track for picture (sorted by `timeline_start`); timeline gaps become black + silent segments (`scripts/timeline_format.py`, `flatten_v2_to_v1_segments` / `TIMELINE_GAP_SOURCE`; `scripts/media.py`)

## Renderer notes

- **v1**: unchanged — concat segments in order
- **v2**: video track sorted by `timeline_start`; per-clip **`speed`**, **`volume`**, and **`zoom`** are applied in FFmpeg (`scripts/media.py`). Top-level **`settings`** is stored on plans but the renderer still uses built-in **1080×1920 @ 30 fps** constants until it reads `settings`.
- **`--captions`**: still builds word captions from video cuts + transcripts (same as v1 flatten)
