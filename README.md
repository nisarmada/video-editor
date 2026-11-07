# AI Video Editor

Local Python tools for probing, cutting, joining, transcribing, indexing, and tightening raw footage.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python --version   # should be 3.12.x
```

Put original clips in `footage/`. Run scripts from the project root with the venv activated.

## API server (FastAPI)

```bash
python scripts/make_proxies.py          # optional: pre-cache 540p proxies
uvicorn backend.main:app --reload --app-dir .
```

See `backend/README.md` for endpoints (footage, timelines, edit ops, planner, render).

**Web UI:** `frontend/README.md` — run FastAPI + Vite together (`npm run dev` proxies `/api`).

Requires [FFmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on your PATH).  
**Captions:** Homebrew’s minimal `ffmpeg` often lacks `libass`/`drawtext`. The renderer falls back to PNG overlays automatically. For native ASS burn-in, install a build with libass.

## Milestone 1 — probe, cut, join

```bash
python scripts/probe.py footage/my_clip.mov
python scripts/cut.py footage/my_clip.mov 2 7 output/test_cut.mp4
python scripts/join.py output/reel.mp4 footage/a.mov footage/b.mov
```

## Milestone 2 — transcribe

```bash
python scripts/transcribe.py footage/my_clip.mp4
python scripts/transcribe.py footage/my_clip.mp4 --force
```

## Milestone 3 — tighten

```bash
python scripts/silences.py footage/my_clip.mp4
python scripts/tighten_plan.py footage/my_clip.mp4
python scripts/render.py plans/my_clip_tight.json output/my_clip_tight.mp4
python scripts/tighten.py footage/my_clip.mp4
```

## Media bin — video and audio

The editor treats **`footage/`** as the library. You can import **video** (`.mp4`, `.mov`, …) or **standalone audio** (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`, …). Audio-only files get a **black silent-video proxy** for preview and the same waveform cache as video. The AI planner (`plan.py`) still indexes **video-only** clips for merged `index/` context.

## Milestone 4 — index (no API key)

```bash
python scripts/shots.py footage/my_clip.mp4
python scripts/keyframes.py footage/my_clip.mp4
python scripts/index_clip.py footage/my_clip.mp4
```

AI descriptions of keyframe images (requires `ANTHROPIC_API_KEY` in `.env`):

```bash
python scripts/caption_frames.py footage/my_clip.mp4
python scripts/index_clip.py footage/my_clip.mp4 --force
```

Merged file: `index/my_clip.json` includes transcript, shots, keyframes, and frame captions when present.

## Captions on rendered edits

Word timestamps are remapped to the **edited** timeline (after cuts):

```bash
python scripts/captions.py plans/my_clip_tight.json
python scripts/render.py plans/my_clip_tight.json output/my_clip_tight.mp4 --captions
```

Edit look-and-feel in constants at the top of `scripts/captions.py`.

## Timeline v2 (CapCut-style, no UI yet)

See `docs/timeline_v2.md`. Convert v1 → v2:

```bash
python scripts/convert_v1_to_v2.py plans/draft1.json plans/draft1_v2.json
python scripts/render.py plans/draft1_v2.json output/draft1_v2.mp4
```

## Plan validation

```bash
python scripts/validate_plan.py plans/my_clip_tight.json --max-length 30
```

`render.py` validates automatically before encoding.

## Milestone 5 — AI plan from brief

```bash
python scripts/plan.py --brief "30s reel, hook in first 2 seconds, casual vibe" --out plans/draft1.json
python scripts/validate_plan.py plans/draft1.json --max-length 32
python scripts/render.py plans/draft1.json output/draft1.mp4 --captions
```

`plan.py` saves **schema v2** (Claude still returns v1 segments; conversion runs after validation). Hand-written v1 plans: `convert_v1_to_v2.py`.

Set `ANTHROPIC_PLAN_MODEL` in `.env` (default `claude-sonnet-5-5`).

### Reference style for the planner

Put a reference video under `references/` (not under `footage/`, which stays read-only for originals), then build a profile the UI can use:

```bash
python scripts/analyze_style.py references/my_ref.mp4 --name "Fast Vlog Reference" --out plans/styles/fast_vlog.json
```

Or use **AI Assistant → Drop reference video** in the web UI (saves `references/…` and `plans/styles/<id>.json`). Dropping or choosing **Imitate style** passes that profile into `plan.py`.

Optional: set `ANTHROPIC_STYLE_VISION_MODEL` (default matches `caption_frames`: Haiku vision).

## Cursor as planner (manual test)

1. Index a few clips with `index_clip.py`.
2. Ask Cursor: read `index/*.json`, write `plans/manual_test.json` (same segment format as tighten plans).
3. `python scripts/validate_plan.py plans/manual_test.json`
4. `python scripts/render.py plans/manual_test.json output/manual_test.mp4`

See `PROJECT.md` for the full pipeline.
