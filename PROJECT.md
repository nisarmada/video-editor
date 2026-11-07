# AI Video Editor (personal project)

## Goal
Give the program a folder of raw footage plus a short brief (e.g. "30s
travel reel, hook in first 2 seconds"). It produces a finished, coherent
vertical video (1080x1920) automatically. Later: imitate a creator's
editing style.

## My situation
- I'm a beginner programmer using Cursor. Explain code in comments.
- Personal use only, runs locally on my computer.
- Typical footage: [talking to camera / travel b-roll / ...]

## Tech choices
- Python 3.11+, FFmpeg for all cutting/rendering
- faster-whisper for transcripts (local)
- PySceneDetect for shot boundaries
- Anthropic API (Claude) for planning and captioning keyframes
- Local FastAPI API (`backend/`) + Vite/React frontend (`frontend/`); otherwise no database. Everything stays files and JSON.

## Pipeline (one script per stage, each reads/writes JSON)
1. ingest: per clip, make proxy, transcript with word timestamps,
   silence markers, shot cuts (video), keyframes + AI captions (video) -> index/<clip>.json
   merged `index/<stem>.json`; audio-only files get transcript + silences (no shots/keyframes).
   Upload/rescan triggers background analysis (`POST /api/footage/analyze` for manual queue).
2. plan: unified **media catalog** (all footage types) + brief to Claude -> schema v2 timeline JSON
3. validate: check the timeline (times exist, length is right, no overlaps)
4. render: timeline JSON -> video via FFmpeg
5. review: extract frames from the draft, Claude critiques, optional revision

## Timeline format (the central contract)
**v1:** a JSON list (or object with `segments`): `{source, start, end, caption?, zoom?, ...}` — concatenated in order.

**v2 (editor):** multi-track `{schema_version: 2, tracks: [{type: video|audio|caption, clips: [...]}]}` — see `docs/timeline_v2.md`.

Convert: `python scripts/convert_v1_to_v2.py plans/old.json plans/new_v2.json`

`plan.py` asks Claude for v1 segments, validates, then saves schema v2 (`created_by: ai`, one `group_id` per run). Validate and render accept both v1 and v2 files.

## Folder structure
footage/    original clips (NEVER modify or delete)
index/      analysis JSON per clip
plans/      timeline JSONs
output/     rendered videos
scripts/    pipeline code
frontend/   local web UI (Vite + React + TypeScript)
backend/    FastAPI server for UI and tools

## Rules
- Build one milestone at a time; each must run on its own before moving on.
- Test with short clips (under 30s).
- Never hard-code API keys; use .env.
- Cache everything expensive (transcripts, AI captions). Don't redo work.
- Print clear progress messages and readable errors.

## Current milestone
**UI playback** — local web editor (`frontend/`) with media bin + proxy preview + read-only v2 timeline; `backend/` serves footage and plans. Next: timeline editing, then render + review loop.

### Frontend session state (before milestone 5a — editing)
Zustand `useTimelineStore` holds **`timeline`** (v2, server-loaded), **`playheadSeconds`**, **`selectedClipId`**, **`undoStack`** / **`redoStack`** (inverse op payloads), **`applyOperationInProgress`**, **`dragInProgress`** (future trim drag), and UI-only fields (zoom, playing). **All timeline mutations** must go through **`applyOperation({ operation, arguments })`**, which `POST`s to `/api/timeline/apply-op`, then **replaces `timeline`** with the response `timeline`; each success **pushes `undo` onto `undoStack`** and **clears `redoStack`**. **`undo` / `redo`** pop a stack and `POST` **`apply_undo`** with `{ undo: <payload> }` so the server runs `timeline_ops.apply_undo`. **⌘Z** / **⌘⇧Z** mirror `undo` / `redo`. Mutations are skipped while **`applyOperationInProgress`** or **`dragInProgress`** is true. Higher-level helpers like **`splitAtPlayhead`** / **`deleteSelectedClip`** call `applyOperation` only.

## Later ideas (don't build yet)
Style profile from reference creators, beat-synced cuts, music, captions
styling, export to FCPXML, a simple UI.