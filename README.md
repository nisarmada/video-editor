# AI Video Editor

Local Python tools for probing, cutting, joining, transcribing, and tightening raw footage.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python --version   # should be 3.12.x
```

Put original clips in `footage/` (video files are gitignored; the folder stays in git). Run scripts from the project root with the venv activated.

**Sidebar:** If you do not see `.mp4` files under `footage/`, run `ls -lh footage/` in the terminal, or use **Developer: Reload Window**. This repo sets `explorer.excludeGitIgnore` to false so clips should appear. Do not open raw `.mp4` files in the text editor — use Finder/Quick Look or play `output/` results instead.

Requires [FFmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on your PATH).

## Milestone 1 — probe, cut, join

### Probe a clip

```bash
python scripts/probe.py footage/my_clip.mov
```

### Cut a segment

```bash
python scripts/cut.py footage/my_clip.mov 2 7 output/test_cut.mp4
```

### Join clips

```bash
python scripts/join.py output/reel.mp4 footage/clip_a.mov footage/clip_b.mov
```

## Milestone 2 — transcribe

```bash
python scripts/transcribe.py footage/my_clip.mp4
# Re-run: python scripts/transcribe.py footage/my_clip.mp4 --force
```

Writes `index/<clip>_transcript.json` (cached; use `--force` to refresh).

## Milestone 3 — tighten (remove dead air)

Step by step:

```bash
python scripts/silences.py footage/my_clip.mp4
# Noisy background? Try: --noise -25
# If ffmpeg still finds no silences, tighten_plan uses pauses from the transcript word timestamps.

python scripts/tighten_plan.py footage/my_clip.mp4
# Optional filler removal: --remove-fillers

python scripts/render.py plans/my_clip_tight.json output/my_clip_tight.mp4
```

One command (transcribe + silences + plan + render, uses cached index files when present):

```bash
python scripts/tighten.py footage/my_clip.mp4
python scripts/tighten.py footage/my_clip.mp4 --remove-fillers
python scripts/tighten.py footage/my_clip.mp4 --force-index
```

See `PROJECT.md` for the full pipeline plan.
