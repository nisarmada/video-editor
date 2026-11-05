# AI Video Editor

Local Python tools for probing, cutting, and joining raw footage (Milestone 1).

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version   # should be 3.12.x
```

Put original clips in `footage/` (video files are gitignored; the folder stays in git). Run scripts from the project root with the venv activated.

**Sidebar:** If you do not see `.mp4` files under `footage/`, run `ls -lh footage/` in the terminal, or use **Developer: Reload Window**. This repo sets `explorer.excludeGitIgnore` to false so clips should appear. Do not open raw `.mp4` files in the text editor — use Finder/Quick Look or play `output/` results instead.

Requires [FFmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on your PATH).

## Scripts

### Probe a clip

Prints duration, resolution, fps, and whether audio is present.

```bash
python scripts/probe.py footage/my_clip.mov
```

### Cut a segment

Re-encodes the segment (frame-accurate, H.264 + AAC). Output cannot go inside `footage/`.

```bash
python scripts/cut.py footage/my_clip.mov 2 7 output/test_cut.mp4
```

### Join clips

Normalizes each input to 1080×1920 vertical at 30 fps (letterboxed, not stretched), then concatenates.

```bash
python scripts/join.py output/reel.mp4 footage/clip_a.mov footage/clip_b.mov
```

See `PROJECT.md` for the full pipeline plan.
