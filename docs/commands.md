# Timeline edit commands (schema v2)

Pure edit operations for multi-track timelines. All commands take a **v2 timeline object** (see `timeline_v2.md`) and return:

```json
{
  "timeline": { "...": "updated v2 plan" },
  "undo": { "op": "...", "...": "args to reverse this edit" }
}
```

Apply undo by invoking the operation named in `undo.op` with the stored arguments (see per-command tables). No file I/O in the op layer.

## Global rules

1. **No overlaps on a track** — After every successful edit, clips on each track have disjoint timeline intervals. Touching edges (`A` ends exactly when `B` starts) are allowed.
2. **Minimum clip length** — `source_out - source_in` must be at least **0.3s** on video/audio (same as validation). Caption clips with both `source_in` and `source_out` follow the same minimum when those fields are present.
3. **Timeline duration** — For video/audio: `(source_out - source_in) / speed` (default `speed` = 1.0). Caption duration uses source span when set.
4. **Split metadata** — `split_clip` copies `created_by`, `group_id`, and optional fields (`zoom`, `speed`, `volume`, `text`, `caption`, …) to both parts. The **left** part keeps the original clip `id`; the **right** part gets a new `id`.
5. **Merge preconditions** — `merge_clips` only succeeds when:
   - Both clips are on the **same track**.
   - They are **adjacent on the timeline** (no gap, no overlap).
   - Same `source` path.
   - **Contiguous in source time**: `left.source_out` ≈ `right.source_in` (within 1ms).
   - Order is determined by `timeline_start` (caller may pass ids in either order).

## Commands

### `split_clip`

Split one clip at a **timeline** time (seconds, absolute on the timeline).

| Argument | Type | Description |
|----------|------|-------------|
| `clip_id` | string | Clip to split |
| `at_timeline_time` | float | Must lie strictly inside the clip’s timeline span |

**Effect:** Two clips; left keeps `id`, right gets new `id`. Source split:  
`source_split = source_in + (at_timeline_time - timeline_start) * speed`.

**Undo:**

```json
{ "op": "merge_clips", "clip_id_a": "<left_id>", "clip_id_b": "<right_id>" }
```

---

### `trim_clip`

Change `source_in` and/or `source_out` without moving `timeline_start` (trim from head/tail in source media).

| Argument | Type | Description |
|----------|------|-------------|
| `clip_id` | string | Target clip |
| `source_in` | float, optional | New in-point (must increase toward `source_out`) |
| `source_out` | float, optional | New out-point (must decrease from old out) |

At least one of `source_in` / `source_out` must be provided.

**Undo:** restores previous `source_in` / `source_out`:

```json
{
  "op": "trim_clip",
  "clip_id": "...",
  "source_in": 1.0,
  "source_out": 5.0
}
```
(Omit keys that were not changed.)

---

### `move_clip`

Change placement on the timeline and/or move to another track.

| Argument | Type | Description |
|----------|------|-------------|
| `clip_id` | string | Clip to move |
| `timeline_start` | float, optional | New start time |
| `track_id` | string, optional | Destination track `id` |

At least one of `timeline_start` / `track_id` must be provided.

**Undo:**

```json
{
  "op": "move_clip",
  "clip_id": "...",
  "timeline_start": 0.0,
  "track_id": "track-video-main"
}
```

---

### `delete_clip`

Remove a clip from its track.

| Argument | Type | Description |
|----------|------|-------------|
| `clip_id` | string | Clip to remove |

**Undo:**

```json
{
  "op": "add_clip",
  "track_id": "...",
  "clip": { "...": "full clip object as before delete" }
}
```

---

### `add_clip`

Insert a clip onto a track.

| Argument | Type | Description |
|----------|------|-------------|
| `track_id` | string | Target track |
| `clip` | object | Full clip (must include unique `id`) |

**Undo:**

```json
{ "op": "delete_clip", "clip_id": "<clip.id>" }
```

---

### `merge_clips`

Merge two adjacent clips into one (see merge preconditions).

| Argument | Type | Description |
|----------|------|-------------|
| `clip_id_a` | string | First clip id |
| `clip_id_b` | string | Second clip id |

**Effect:** Single clip with `id` of the **left** (earlier) clip, `source_in` from left, `source_out` from right, `timeline_start` from left.

**Undo:**

```json
{
  "op": "split_clip",
  "clip_id": "<merged_id>",
  "at_timeline_time": <timeline time at former boundary>
}
```

---

### `set_clip_property`

Set one or more optional fields on a clip (not for moving or retiming — use `move_clip` / `trim_clip`).

Allowed keys include: `zoom`, `speed`, `volume`, `text`, `caption`, `group_id`, `created_by`.  
Cannot set `id`, `timeline_start`, `source`, `source_in`, or `source_out` (use other ops).

| Argument | Type | Description |
|----------|------|-------------|
| `clip_id` | string | Target clip |
| `properties` | object | Keys to set |

**Undo:**

```json
{
  "op": "set_clip_property",
  "clip_id": "...",
  "properties": { "zoom": 1.0 }
}
```
(Only keys that were changed; values are **previous** values.)

---

## Python API

Implemented in `scripts/timeline_ops.py`:

```python
from timeline_ops import split_clip, trim_clip, move_clip, delete_clip, add_clip, merge_clips, set_clip_property

result = split_clip(timeline, clip_id="...", at_timeline_time=2.5)
new_timeline = result["timeline"]
undo = result["undo"]
```

Each function raises `ValueError` with a short message if preconditions fail.
