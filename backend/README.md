# Video editor API

Local FastAPI server for a future UI.

## Setup

From the repo root (with `.venv` active):

```bash
pip install -r requirements.txt
python scripts/make_proxies.py   # optional: pre-build 540p proxies
uvicorn backend.main:app --reload --app-dir .
```

Open `http://127.0.0.1:8000/docs` for interactive API docs.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness check |
| GET | `/api/footage` | List clips + proxy/thumbnail URLs |
| GET | `/api/footage/{name}/proxy` | Stream 540p proxy (builds on first request) |
| GET | `/api/footage/{name}/thumbnail` | JPEG poster |
| GET | `/api/plans` | List saved timelines |
| GET | `/api/plans/{name}` | Load v2 timeline JSON |
| PUT | `/api/plans/{name}` | Save v2 timeline (validated) |
| POST | `/api/timeline/apply-op` | Run `timeline_ops` on a timeline |
| POST | `/api/planner/run` | Claude planner → v2 plan on disk |
| POST | `/api/render` | FFmpeg export to `output/` |
| GET | `/api/output/{name}` | Download rendered MP4 |

Set `VIDEO_EDITOR_ROOT` to point at the repo if the process cwd is not the project root.
