"""
FastAPI backend for the video editor.

Run from repo root:
  uvicorn backend.main:app --reload --app-dir .
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from backend.paths import ProjectPaths, get_paths, set_paths  # noqa: E402
from plan import generate_plan  # noqa: E402
from proxy_media import (  # noqa: E402
    ensure_proxy,
    ensure_thumbnail,
    footage_entry,
    list_footage_files,
    proxy_path_for_clip,
    thumbnail_path_for_clip,
)
from render_core import render_plan_data, render_plan_file  # noqa: E402
from timeline_format import is_v2  # noqa: E402
from timeline_ops import dispatch_operation  # noqa: E402
from validate_plan import validate_plan_data  # noqa: E402

app = FastAPI(title="Video Editor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def project_cwd(paths: ProjectPaths):
    """Pipeline scripts expect cwd = repo root."""
    prev = os.getcwd()
    os.chdir(paths.root)
    try:
        yield
    finally:
        os.chdir(prev)


class ApplyOpRequest(BaseModel):
    timeline: dict[str, Any]
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SaveTimelineRequest(BaseModel):
    timeline: dict[str, Any]


class PlannerRequest(BaseModel):
    brief: str
    save_as: str = Field(description="Plan filename without path, e.g. draft1")


class RenderRequest(BaseModel):
    plan_name: str | None = None
    timeline: dict[str, Any] | None = None
    output: str = Field(description="Output filename under output/, e.g. export.mp4")
    captions: bool = False
    max_length: float | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/footage")
def list_footage(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    clips = list_footage_files(paths.root)
    return {"clips": [footage_entry(paths.root, p) for p in clips]}


@app.get("/api/footage/{name}/proxy")
def serve_proxy(name: str, paths: ProjectPaths = Depends(get_paths)) -> FileResponse:
    try:
        clip = paths.safe_footage_name(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Footage not found")
    try:
        proxy = ensure_proxy(paths.root, clip)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(proxy, media_type="video/mp4", filename=proxy.name)


@app.get("/api/footage/{name}/thumbnail")
def serve_thumbnail(name: str, paths: ProjectPaths = Depends(get_paths)) -> FileResponse:
    try:
        clip = paths.safe_footage_name(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Footage not found")
    try:
        thumb = ensure_thumbnail(paths.root, clip)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(thumb, media_type="image/jpeg", filename=thumb.name)


@app.get("/api/plans")
def list_plans(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    paths.plans.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in paths.plans.glob("*.json"))
    return {"plans": names}


@app.get("/api/plans/{name}")
def load_timeline(name: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    path = paths.plan_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Plan not found")
    data = json.loads(path.read_text())
    if not is_v2(data):
        raise HTTPException(status_code=400, detail="Plan is not schema v2")
    return data


@app.put("/api/plans/{name}")
def save_timeline(
    name: str,
    body: SaveTimelineRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, str]:
    if not is_v2(body.timeline):
        raise HTTPException(status_code=400, detail="timeline must be schema_version 2")
    with project_cwd(paths):
        errors = validate_plan_data(body.timeline, None)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    path = paths.plan_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body.timeline, indent=2, ensure_ascii=False) + "\n")
    return {"saved": path.name}


@app.post("/api/timeline/apply-op")
def apply_operation(body: ApplyOpRequest) -> dict[str, Any]:
    try:
        result = dispatch_operation(body.timeline, body.operation, body.arguments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/api/planner/run")
def run_planner(
    body: PlannerRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    with project_cwd(paths):
        try:
            plan_v2, group_id, usage = generate_plan(body.brief)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except ValueError as e:
            detail = e.args[0] if e.args and isinstance(e.args[0], list) else str(e)
            raise HTTPException(status_code=400, detail=detail)

    path = paths.plan_file(body.save_as)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan_v2, indent=2, ensure_ascii=False) + "\n")
    return {
        "plan_name": path.name,
        "group_id": group_id,
        "usage": usage,
        "timeline": plan_v2,
    }


@app.post("/api/render")
def render_export(
    body: RenderRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, str]:
    if not body.plan_name and not body.timeline:
        raise HTTPException(status_code=400, detail="Provide plan_name or timeline")

    out_path = paths.output_file(body.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with project_cwd(paths):
        try:
            if body.timeline is not None:
                plan_path = None
                if body.captions and body.plan_name:
                    plan_path = paths.plan_file(body.plan_name)
                render_plan_data(
                    body.timeline,
                    out_path,
                    root=paths.root,
                    captions=body.captions,
                    max_length=body.max_length,
                    plan_path_for_captions=plan_path,
                )
            else:
                assert body.plan_name
                render_plan_file(
                    paths.plan_file(body.plan_name),
                    out_path,
                    root=paths.root,
                    captions=body.captions,
                    max_length=body.max_length,
                )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            detail = e.args[0] if e.args and isinstance(e.args[0], list) else str(e)
            raise HTTPException(status_code=400, detail=detail)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    return {
        "output": str(out_path.relative_to(paths.root)),
        "url": f"/api/output/{out_path.name}",
    }


@app.get("/api/output/{name}")
def serve_output(name: str, paths: ProjectPaths = Depends(get_paths)) -> FileResponse:
    base = Path(name).name
    path = paths.output / base
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")
    return FileResponse(path, media_type="video/mp4", filename=base)


__all__ = ["app", "set_paths"]
