# Local web editor — UI specification

CapCut-style editor for **1080×1920** vertical reels. Runs in the browser against the local FastAPI backend (`backend/`). Timelines use **schema v2** (`docs/timeline_v2.md`). Edits map to **`timeline_ops`** commands (`docs/commands.md`).

This document is **design only** — no frontend implementation yet.

---

## Principles

1. **Backend is the source of truth for all edits.** The UI never treats a locally mutated timeline as canonical. Every change goes through the API; the UI replaces its working copy with the **`timeline`** returned from the server (validated on save and after each op).
2. **Preview uses proxies, export uses originals.** List and stream **540p proxies** from `/api/footage/{name}/proxy`. Full-quality render is explicit via `/api/render`.
3. **One open plan.** The user edits a named plan under `plans/` (e.g. `draft1.json`), loaded with `GET /api/plans/{name}` and persisted with `PUT /api/plans/{name}` after meaningful checkpoints (see Save below).
4. **No overlap on a track.** The server rejects invalid states; the UI should prevent obvious overlaps while dragging but must handle validation errors gracefully.

---

## Screen layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [App bar: plan name · Save · Export · Run planner…]                        │
├──────────────┬──────────────────────────────┬───────────────────────────────┤
│              │                              │                               │
│  Media bin   │      Preview player          │   Properties panel            │
│  (top left)  │      (top center)            │   (top right)                 │
│              │                              │                               │
│  ~25% width  │      ~50% width              │   ~25% width                  │
│              │                              │                               │
├──────────────┴──────────────────────────────┴───────────────────────────────┤
│  Timeline toolbar (tools, zoom, snap, undo/redo, split, delete, merge…)     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Timeline (full width, remaining height)                                    │
│  — ruler, playhead, track headers, clip blocks                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Media bin (top left)

- Lists clips from `GET /api/footage`: thumbnail, filename, duration, optional index hints later.
- **Click** a bin item: load its proxy in the preview for **source scrubbing** (not timeline mode) or arm it for **drag to timeline**.
- **Double-click** (optional): quick-add full source range to the end of the video track (via `add_clip`), subject to validation.

### Preview player (top center)

- **Timeline mode:** Shows the composite at the **playhead** time — which video clip is active on the video track, mapped source time from `source_in` + (playhead − `timeline_start`) × `speed`.
- **Source mode:** When inspecting bin media, scrubs the selected file’s proxy only.
- Standard controls: play/pause, loop, timecode, **playhead synced to timeline** (bi-directional: scrubbing preview moves playhead when in timeline mode).
- Vertical safe-area overlay (9:16) optional guide.

### Properties panel (top right)

- Context-sensitive:
  - **No selection:** Plan metadata (`name`, `brief`, `target_length_seconds`, `settings`).
  - **Clip selected:** `source` (read-only path), `source_in` / `source_out` (numeric or linked to trim handles), optional `zoom`, `speed`, `volume`, `caption` / `text`, `created_by`, `group_id` (read-only for AI groups until accepted).
- Property edits that are allowed by `set_clip_property` commit via `POST /api/timeline/apply-op` on blur or Enter — not on every keystroke if that causes churn.
- Trimming via numbers uses `trim_clip`; moving start on timeline uses `move_clip`.

### Timeline (bottom, full width)

- **Toolbar** directly above the track area (see Timeline toolbar).
- **Ruler** in seconds (and optionally frame ticks from `settings.fps`).
- **Playhead** — vertical line, draggable; shared with preview.
- **Tracks** — default rows from v2 plan:
  - **Video** (required for export)
  - **Audio** (may be empty; UI still shows row)
  - **Caption** (text clips)
- Track headers: label, mute/solo placeholders (no-op until mixer exists), lock (future).
- Clips drawn as horizontal blocks: width = timeline duration; label = filename and/or caption snippet.

### Timeline toolbar

Left to right (suggested):

| Control | Action |
|--------|--------|
| Selection tool | Default; click to select clip |
| Split | Split selected clip at playhead (`split_clip`) |
| Delete | Delete selected clip(s) (`delete_clip`) |
| Merge | Merge two selected adjacent clips (`merge_clips`) when allowed |
| Undo / Redo | See Undo/redo |
| Snap toggle | Enable snap to playhead and clip edges |
| Zoom out / in | Change **timeline pixels per second** (view only) |
| Fit | Zoom so full sequence visible |

Optional later: **Run planner**, **Export**, **Save** duplicates of app bar actions.

---

## Time ↔ pixels

- User-adjustable **zoom**: `pxPerSecond` (or equivalent) affects only the view, not the JSON.
- Clip horizontal position: `timeline_start × pxPerSecond`.
- Clip width: `timeline_duration × pxPerSecond` (respect `speed` for video/audio per `timeline_v2.md`).
- Minimum clip width on screen: clamp with tooltip showing true duration when zoomed out far.

---

## Interactions

### Select clip

- **Click** a clip block: single selection (clear others). Selected clip shows outline; properties panel binds to it.
- **Shift-click** (optional v2): multi-select for delete only; merge requires exactly two adjacent compatible clips.
- Selection is **UI state only** — no API call until an edit runs.
- Clicking empty timeline clears selection.

### Playhead

- Dragging the playhead updates **current time** `t` (seconds, absolute on timeline).
- With snap on, playhead snaps to clip in/out edges and other snap targets when within a **snap threshold** (e.g. 8 px converted to seconds at current zoom).

### Split at playhead

- **Shortcut / toolbar Split** when exactly one clip is selected and playhead time `t` lies **strictly inside** that clip’s timeline span:
  - `POST /api/timeline/apply-op` with `operation: "split_clip"`, `arguments: { clip_id, at_timeline_time: t }`.
- If playhead is outside the clip or on an edge, show inline message (server would reject per `commands.md`).
- After success: server returns new `timeline`; UI selects the **left** segment (same `id` as before split).

### Delete

- **Delete** or Backspace with selection: `delete_clip` per selected clip (order: by timeline position; each op uses latest `timeline` from previous response).
- Or batch: UI may send sequential ops; backend remains authoritative after each step.

### Drag to move (clip along track / between tracks)

- **Drag clip body** horizontally: live ghost follows mouse; on **drop**, compute new `timeline_start` from pixel position (apply snap).
- **Drop on another track row** (same type rules): include `track_id` in `move_clip`.
- **During drag:** optional ghost preview only — **commit on drop** with one `move_clip` call.
- If drop would overlap a neighbor, server returns 400; UI reverts ghost and shows error.

### Drag edges to trim

- **Left handle:** adjusts `source_in` (head trim); `timeline_start` may increase if UI implements “trim and ripple” later — **v1 UI: head trim only changes `source_in`**, clip stays fixed at same `timeline_start` (matches `trim_clip` in `commands.md`).
- **Right handle:** adjusts `source_out` (tail trim).
- Live drag updates a **local preview** of in/out; **mouseup** sends `trim_clip` with final `source_in` and/or `source_out`.
- Enforce minimum duration **0.3 s**; show server error if violated.

### Snap to playhead and clip edges

When **Snap** is on:

- Moving a clip: `timeline_start` snaps to playhead, to **start/end of other clips** on the same track, and to **0**.
- Trimming: `source_in` / `source_out` mapping from edge drag may snap the **timeline edge** to playhead or adjacent clip boundaries where applicable.
- Visual: brief highlight on snap targets when pointer is within threshold.

### Zoom the timeline

- Toolbar +/- or pinch (trackpad): change `pxPerSecond` only.
- Scroll wheel + modifier (e.g. Alt): zoom centered on cursor time.
- **Fit** sets zoom so `[0, sequenceEnd]` fits in viewport; `sequenceEnd` = max end time across all tracks.

### Undo / redo

- Each successful `apply-op` returns an **`undo`** payload (`docs/commands.md`).
- **Undo stack (client):** push `undo` after each edit; **undo** executes by calling `apply-op` with `operation` and `arguments` from that payload (same contract as inverse ops documented per command).
- **Redo stack:** push the inverse of undo when undo succeeds, or store paired redo payloads — implementation detail, but **each redo is still one server `apply-op`**.
- Loading a plan from disk or **Accept/Undo AI group** clears or branches stacks (product choice: clear on load; document in UI copy).
- **Save** does not replace undo history unless the user chooses “Revert to saved.”

### Merge adjacent clips

- User selects **two clips** on the **same track** (or selects one and Shift-clicks neighbor).
- **Merge** enabled only when preconditions hold (`commands.md`): adjacent on timeline, same `source`, contiguous `source_in`/`source_out`.
- Action: `merge_clips` with both clip ids.
- Optional UX: hover between two touching same-source segments shows a “merge” affordance.

### Drag from media bin to timeline

1. User drags bin item onto a track row at time `t` (from drop x → seconds, with snap).
2. On drop, UI builds a new clip object:
   - New UUID `id`
   - `source`: `footage/{filename}`
   - Default `source_in`: 0; `source_out`: min(full duration, sensible default cap) from footage metadata
   - `timeline_start`: `t`
   - `created_by`: `"user"`
   - No `group_id` unless user is pasting into an AI group (not in v1)
3. `add_clip` with `track_id` of drop target.
4. Video drops go to video track; future: restrict caption/audio drops by track type.

---

## AI edits (Claude planner)

When the user runs **`POST /api/planner/run`**, the saved plan contains clips with `created_by: "ai"` and a shared **`group_id`** for that planner run (see `PROJECT.md`).

### Visual treatment

- Clips with **`created_by === "ai"`** use a **distinct tint** (e.g. soft purple/blue fill and border) vs neutral gray for **`user`** clips.
- Clips sharing the same **`group_id`** show a **group bracket** or shared top bar in the timeline (all tracks that contain that group’s clips align visually).
- Planner may add video + caption clips with the same `group_id`; bracket spans all affected tracks.

### Accept and Undo (per group)

Each **`group_id`** from an AI run shows a floating group header or context row:

| Button | Behavior |
|--------|----------|
| **Accept** | Marks the group as approved: set `created_by` to `"user"` on **all clips** with that `group_id` (via `set_clip_property` per clip, or one batch of ops). Optionally clear `group_id` or keep for history — default: keep `group_id`, only flip `created_by`. Then **`PUT /api/plans/{name}`** to persist. Tint updates to user style. |
| **Undo group** | Removes **all clips** belonging to that `group_id` on **all tracks** (sequence of `delete_clip` ops, or reload plan snapshot taken before planner run). Preferred v1: UI stored **pre-planner timeline JSON** when planner started; Undo group restores via **`PUT`** full timeline snapshot (still server-validated) rather than many deletes. |

If the user edits individual AI clips before Accept, clips remain tinted until Accept; partial acceptance is **not** in v1 — Accept applies to the whole `group_id`.

Running the planner again on the same plan adds clips with a **new** `group_id`; older AI groups remain visible until Accepted or Undone.

---

## Save, load, export, planner

| User action | API |
|-------------|-----|
| Open project / plan | `GET /api/plans/{name}` → replace UI timeline |
| Save | `PUT /api/plans/{name}` with current `timeline` (after last successful op) |
| Export video | `POST /api/render` with `plan_name` and `output`; poll or wait; link to `GET /api/output/{name}` |
| Run planner | Dialog for brief → `POST /api/planner/run` → reload plan or merge response `timeline` into editor |

Auto-save (optional): debounced `PUT` after each successful `apply-op` — still server-validated.

---

## Edit operation mapping (summary)

| UI gesture | `operation` | Notes |
|------------|-------------|--------|
| Split at playhead | `split_clip` | `at_timeline_time` = playhead |
| Delete selection | `delete_clip` | |
| Move / drop clip | `move_clip` | `timeline_start`, optional `track_id` |
| Trim handles | `trim_clip` | `source_in` / `source_out` |
| Bin → timeline | `add_clip` | New clip + `track_id` |
| Merge | `merge_clips` | Two clip ids |
| Property fields | `set_clip_property` | Allowed keys only |
| Accept AI group | `set_clip_property` × N | `created_by: "user"` |

All via **`POST /api/timeline/apply-op`** unless Undo group uses full **`PUT`** restore.

---

## Error and loading states

- **400** from apply-op / save: show validation messages (overlap, min length, missing source).
- **503** on planner: missing API key or upstream error.
- **500** on render/proxy: FFmpeg failures; keep timeline intact.
- While awaiting API: disable destructive toolbar buttons; show spinner on preview if render blocks.

---

## Out of scope (first UI version)

- Beat sync, transitions, gap fill with black on render
- Ripple / roll trim; multi-track audio mix
- Real-time collaborative editing
- Direct writes to `footage/` or bypassing the API for timeline changes

---

## Related docs

- `PROJECT.md` — pipeline and folders  
- `docs/timeline_v2.md` — JSON schema  
- `docs/commands.md` — edit ops and undo payloads  
- `backend/README.md` — HTTP endpoints  
