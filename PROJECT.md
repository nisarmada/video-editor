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
- No web framework, no database. Everything is files and JSON.

## Pipeline (one script per stage, each reads/writes JSON)
1. ingest: per clip, make proxy, transcript with word timestamps,
   silence markers, shot cuts, keyframes + AI captions -> index/<clip>.json
2. plan: send indexes + brief to Claude, get back a timeline JSON
3. validate: check the timeline (times exist, length is right, no overlaps)
4. render: timeline JSON -> video via FFmpeg
5. review: extract frames from the draft, Claude critiques, optional revision

## Timeline format (the central contract)
**v1:** a JSON list (or object with `segments`): `{source, start, end, caption?, zoom?, ...}` — concatenated in order.

**v2 (editor):** multi-track `{schema_version: 2, tracks: [{type: video|audio|caption, clips: [...]}]}` — see `docs/timeline_v2.md`.

Convert: `python scripts/convert_v1_to_v2.py plans/old.json plans/new_v2.json`

The AI planner still outputs v1 today; validate and render accept both.

## Folder structure
footage/    original clips (NEVER modify or delete)
index/      analysis JSON per clip
plans/      timeline JSONs
output/     rendered videos
scripts/    pipeline code

## Rules
- Build one milestone at a time; each must run on its own before moving on.
- Test with short clips (under 30s).
- Never hard-code API keys; use .env.
- Cache everything expensive (transcripts, AI captions). Don't redo work.
- Print clear progress messages and readable errors.

## Current milestone
Milestone 5: Claude timeline planning (`scripts/plan.py`). Next: render + review loop.

## Later ideas (don't build yet)
Style profile from reference creators, beat-synced cuts, music, captions
styling, export to FCPXML, a simple UI.