"""
FastAPI backend for the video editor.

Run from repo root:
  uvicorn backend.main:app --reload --app-dir .
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from backend.app_logging import get_logs, last_index, log_event  # noqa: E402
from backend.footage_jobs import get_job, schedule_proxy_work  # noqa: E402
from backend.index_jobs import get_job as get_index_job  # noqa: E402
from backend.index_jobs import schedule_index_pipeline  # noqa: E402
from backend.media_catalog import build_media_catalog  # noqa: E402
from backend.waveform_jobs import (  # noqa: E402
    get_job as get_waveform_job,
    schedule_waveform_work,
    waveform_list_status,
)
from backend.footage_ops import (  # noqa: E402
    ffprobe_validate_media,
    ffprobe_validate_video,
    plans_referencing_footage,
    sanitize_upload_basename,
    unique_footage_path,
    video_extension_allowed,
)
from backend.paths import ProjectPaths, get_paths, refresh_paths_from_settings, set_paths  # noqa: E402
from backend.render_jobs import (  # noqa: E402
    any_active_render,
    bind_progress,
    create_job,
    get_cancel_event,
    get_job_public,
    request_cancel,
    update_job,
)
from backend.caption_style_store import fonts_bundle_dir  # noqa: E402
from backend.retranscribe import clear_transcript_dependent_index  # noqa: E402
from backend.settings_store import (  # noqa: E402
    effective_planner_api_key,
    effective_render_defaults,
    get_public_settings,
    load_raw,
    merge_settings,
    save_raw,
    set_planner_api_key,
)
from backend.storage_cache import (  # noqa: E402
    clear_paid_caption_caches,
    clear_regenerable_caches,
    storage_stats,
)
from analyze_style import analyze_reference_video  # noqa: E402
from plan import generate_plan, prepare_planner_context  # noqa: E402
from proxy_media import (  # noqa: E402
    ensure_proxy,
    ensure_thumbnail,
    footage_entry,
    list_footage_files,
    proxy_is_fresh,
    proxy_path_for_clip,
    thumbnail_is_fresh,
    thumbnail_path_for_clip,
)
from render_core import render_plan_data, render_plan_file  # noqa: E402
from convert_v1_to_v2 import convert as convert_plan_v1_to_v2  # noqa: E402
from index_cache import waveform_path  # noqa: E402
from timeline_format import is_v2, v1_segments_from_data  # noqa: E402
from timeline_ops import dispatch_operation  # noqa: E402
from style_profile import list_style_profiles, slug_style_id  # noqa: E402
from validate_plan import validate_plan_data  # noqa: E402
from caption_style import validate_caption_style_dict  # noqa: E402
from caption_style_resolve import list_builtin_presets, resolve_merged_style_for_plan  # noqa: E402
from captions import build_ass_for_timeline, remap_words, sample_preview_ass  # noqa: E402
from media import ffmpeg_has_libass  # noqa: E402

app = FastAPI(title="Video Editor API", version="1.0.0")

# Load path overrides from persisted settings before first request.
refresh_paths_from_settings()

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
    # If set, only these footage basenames are considered. Unanalyzed files are still omitted.
    clip_filenames: list[str] | None = None
    allow_without_merged_index: bool = Field(
        default=False,
        description="Kept for older clients. Unanalyzed files are never sent.",
    )
    imitate_style_id: str | None = Field(
        default=None,
        description="plans/styles/<id>.json profile to mirror in the system prompt",
    )
    mode: str = Field(
        default="draft",
        description="draft = one compact call. full is not available yet.",
    )


class PlannerEstimateRequest(BaseModel):
    brief: str
    clip_filenames: list[str] | None = None
    imitate_style_id: str | None = None


class RenderRequest(BaseModel):
    plan_name: str | None = None
    timeline: dict[str, Any] | None = None
    output: str = Field(description="Output filename under output/, e.g. export.mp4")
    captions: bool | None = None
    max_length: float | None = None
    video_crf: int | None = Field(
        default=None,
        description="libx264 CRF (lower = higher quality). Uses project default when omitted.",
    )


class SettingsUpdate(BaseModel):
    planner_api_key: str | None = None
    paths: dict[str, str] | None = None
    render_defaults: dict[str, Any] | None = None
    user_caption_styles: list[dict[str, Any]] | None = None
    keybindings: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    audio_cut_refine: dict[str, Any] | None = None
    planner: dict[str, Any] | None = None
    transcription: dict[str, Any] | None = None
    embedding: dict[str, Any] | None = None


class CaptionsAssBody(BaseModel):
    timeline: dict[str, Any]
    style: dict[str, Any] | None = None
    clip_ids: list[str] | None = None
    preview_preset: dict[str, Any] | None = None
    style_target: str | None = None
    style_clip_id: str | None = None




class PlanRenameBody(BaseModel):
    to: str


class PlanDuplicateBody(BaseModel):
    to: str


class FootageAnalyzeBody(BaseModel):
    """Queue full analysis (transcript, silences, optional shots/keyframes, merge index)."""

    names: list[str] | None = Field(
        default=None,
        description="Footage basenames to analyze; omit with all=true",
    )
    all: bool = Field(default=False, description="Analyze every file in footage/")


def _client_host_allowed(request: Request) -> bool:
    h = (request.client.host if request.client else "") or ""
    return h in ("127.0.0.1", "::1", "localhost")


def _merge_footage_job(entry: dict[str, Any]) -> dict[str, Any]:
    name = entry["name"]
    job = get_job(name)
    out = dict(entry)
    if job:
        st = job.get("status")
        err = job.get("error")
        if st == "processing":
            out["process_status"] = "processing"
            out["process_error"] = None
        elif st == "failed":
            out["process_status"] = "failed"
            out["process_error"] = err
    return out


def _enrich_footage_clip(paths: ProjectPaths, clip_path: Path) -> dict[str, Any]:
    """footage_entry + proxy job merge + waveform_status."""
    base = clip_path.name
    entry = footage_entry(paths.root, clip_path)
    merged = _merge_footage_job(entry)
    merged["waveform_status"] = waveform_list_status(paths.root, clip_path)
    wf_job = get_waveform_job(base)
    if wf_job and wf_job.get("status") == "failed":
        merged["waveform_error"] = wf_job.get("error")
    else:
        merged["waveform_error"] = None
    return merged


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/status")
def system_status() -> dict[str, Any]:
    return {
        "ffmpeg_libass": ffmpeg_has_libass(),
        "ffmpeg_subtitles_filter": ffmpeg_has_libass(),
    }


@app.get("/api/fonts")
def list_font_files() -> dict[str, Any]:
    d = fonts_bundle_dir()
    if not d.is_dir():
        return {"fonts": []}
    fonts = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() == ".ttf")
    return {"fonts": fonts, "fontsdir": "/api/fonts/dir"}


@app.get("/api/fonts/dir/{filename}")
def serve_font(filename: str) -> FileResponse:
    base = Path(filename).name
    if base != filename or not base.lower().endswith(".ttf"):
        raise HTTPException(status_code=400, detail="Invalid font name")
    path = fonts_bundle_dir() / base
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Font not found")
    return FileResponse(path, filename=base, media_type="font/ttf")


@app.get("/api/caption-styles")
def caption_styles_list(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    built = list_builtin_presets()
    raw = load_raw(paths.root)
    user = raw.get("user_caption_styles")
    user_list: list[dict[str, Any]] = []
    if isinstance(user, list):
        for x in user:
            if isinstance(x, dict) and x.get("id"):
                user_list.append(x)
    return {"built_in": built, "user": user_list}


def _validate_merged_user_style(body: dict[str, Any]) -> dict[str, Any]:
    from caption_style_resolve import default_caption_style, get_builtin_preset, merge_style_dict

    sid = body.get("id")
    if not isinstance(sid, str) or not sid.strip():
        raise HTTPException(status_code=400, detail="Preset id required")
    pid = body.get("preset")
    base = (
        dict(get_builtin_preset(str(pid)))
        if isinstance(pid, str) and get_builtin_preset(pid)
        else default_caption_style()
    )
    override = {k: v for k, v in body.items() if k not in ("id", "name", "preset")}
    merged = merge_style_dict(base, override)
    err = validate_caption_style_dict(merged, f"user preset {sid}")
    if err:
        raise HTTPException(status_code=400, detail={"errors": err})
    stem = sid.strip()
    out: dict[str, Any] = {"id": stem, "name": body.get("name") or stem}
    for k, v in merged.items():
        if k not in ("id", "name"):
            out[k] = v
    return out


@app.put("/api/caption-styles/user/{style_id}")
def put_user_caption_style(
    style_id: str,
    body: dict[str, Any],
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    body = dict(body)
    body["id"] = style_id
    preset = _validate_merged_user_style(body)
    raw = load_raw(paths.root)
    lst = raw.get("user_caption_styles")
    if not isinstance(lst, list):
        lst = []
    replaced = False
    for i, x in enumerate(lst):
        if isinstance(x, dict) and x.get("id") == style_id:
            lst[i] = preset
            replaced = True
            break
    if not replaced:
        lst.append(preset)
    raw["user_caption_styles"] = lst
    save_raw(paths.root, raw)
    log_event("info", f"Saved user caption preset {style_id}")
    return preset


@app.delete("/api/caption-styles/user/{style_id}")
def delete_user_caption_style(style_id: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, str]:
    raw = load_raw(paths.root)
    lst = raw.get("user_caption_styles")
    if not isinstance(lst, list):
        raise HTTPException(status_code=404, detail="No user presets")
    new_list = [x for x in lst if not (isinstance(x, dict) and x.get("id") == style_id)]
    if len(new_list) == len(lst):
        raise HTTPException(status_code=404, detail="Preset not found")
    raw["user_caption_styles"] = new_list
    save_raw(paths.root, raw)
    return {"deleted": style_id}


@app.post("/api/captions/ass")
def captions_build_ass(body: CaptionsAssBody, paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    """ASS text using the same generator as export (and optional preview_preset for mini-cards)."""
    if body.preview_preset is not None:
        tw = th = None
        tl = body.timeline
        if isinstance(tl.get("settings"), dict):
            s = tl["settings"]
            tw = s.get("width")
            th = s.get("height")
        vw = int(tw) if isinstance(tw, (int, float)) else 1080
        vh = int(th) if isinstance(th, (int, float)) else 1920
        ass = sample_preview_ass(body.preview_preset, video_w=vw, video_h=vh)
        return {"ass": ass, "word_count": 3}

    errs, wrns = validate_plan_data(body.timeline, None)
    if errs:
        raise HTTPException(status_code=400, detail={"errors": errs, "warnings": wrns})
    tl = dict(body.timeline)
    tw = th = None
    if isinstance(tl.get("settings"), dict):
        s = tl["settings"]
        tw = s.get("width")
        th = s.get("height")
    vw = int(tw) if isinstance(tw, (int, float)) else 1080
    vh = int(th) if isinstance(th, (int, float)) else 1920
    target = body.style_target or "plan"
    clip_filter = body.clip_ids
    if target == "clip" and body.style_clip_id and not clip_filter:
        clip_filter = [body.style_clip_id]
    with project_cwd(paths):
        ass = build_ass_for_timeline(
            tl,
            style=body.style,
            clip_ids=clip_filter,
            style_target=target,
            style_clip_id=body.style_clip_id,
            video_w=vw,
            video_h=vh,
        )
        segs = v1_segments_from_data(tl)
        words_ct = remap_words(segs, plan_data=tl)
    if clip_filter:
        allow = set(clip_filter)
        words_ct = [w for w in words_ct if w.get("_clip_id") in allow]
    return {"ass": ass, "word_count": len(words_ct)}


@app.get("/api/logs")
def api_logs(since: int = 0, limit: int = 200) -> dict[str, Any]:
    lim = min(max(limit, 1), 500)
    entries = get_logs(since=since, limit=lim)
    return {"entries": entries, "latest_id": last_index()}


@app.get("/api/settings")
def get_settings(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    return get_public_settings(paths.root)


@app.put("/api/settings")
def put_settings(body: SettingsUpdate, paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body.planner_api_key is not None:
        payload["planner_api_key"] = body.planner_api_key
    if body.paths is not None:
        payload["paths"] = body.paths
    if body.render_defaults is not None:
        payload["render_defaults"] = body.render_defaults
    if body.user_caption_styles is not None:
        payload["user_caption_styles"] = body.user_caption_styles
    if body.keybindings is not None:
        payload["keybindings"] = body.keybindings
    if body.ui is not None:
        payload["ui"] = body.ui
    if body.planner is not None:
        payload["planner"] = body.planner
    if body.audio_cut_refine is not None:
        payload["audio_cut_refine"] = body.audio_cut_refine
    if body.transcription is not None:
        payload["transcription"] = body.transcription
    if body.embedding is not None:
        payload["embedding"] = body.embedding
    log_event("info", "Settings updated (non-secret keys only)")
    merge_settings(paths.root, payload)
    paths2 = refresh_paths_from_settings()
    for d in (paths2.footage, paths2.plans, paths2.output):
        d.mkdir(parents=True, exist_ok=True)
    return get_public_settings(paths2.root)


class PlannerKeyBody(BaseModel):
    api_key: str


@app.put("/api/settings/planner-api-key")
def put_planner_key(
    body: PlannerKeyBody,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, str]:
    set_planner_api_key(paths.root, body.api_key)
    log_event("info", "Planner API key stored (value not logged)")
    return {"ok": "true"}


@app.post("/api/settings/test-planner")
def test_planner(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    key = effective_planner_api_key(paths.root)
    if not key:
        raise HTTPException(status_code=400, detail="Planner API key not configured")
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=8,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
    except Exception as e:
        log_event("warning", f"Planner test failed: {type(e).__name__}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_event("info", "Planner API test succeeded")
    return {"ok": True}


@app.get("/api/footage")
def list_footage(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    clips = list_footage_files(paths.root)
    return {"clips": [_enrich_footage_clip(paths, p) for p in clips]}


@app.post("/api/footage/upload")
async def upload_footage(
    paths: ProjectPaths = Depends(get_paths),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Stream multipart file to footage/ in chunks, validate, queue proxy/thumbnail."""
    raw_name = file.filename or "upload.mp4"
    try:
        base = sanitize_upload_basename(raw_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    paths.footage.mkdir(parents=True, exist_ok=True)
    try:
        dest, final_name = unique_footage_path(paths.footage, base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        with dest.open("wb") as out_f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
    except OSError as e:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        ffprobe_validate_media(dest)
    except RuntimeError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e)) from e

    schedule_proxy_work(
        paths.root,
        dest,
        ensure_proxy=ensure_proxy,
        ensure_thumbnail=ensure_thumbnail,
        proxy_is_fresh=proxy_is_fresh,
        thumbnail_is_fresh=thumbnail_is_fresh,
        proxy_path_for_clip=proxy_path_for_clip,
        thumbnail_path_for_clip=thumbnail_path_for_clip,
    )
    schedule_waveform_work(paths.root, dest)
    schedule_index_pipeline(paths.root, dest)

    return {"clip": _enrich_footage_clip(paths, dest), "saved_as": final_name}


@app.post("/api/footage/rescan")
def rescan_footage(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    """Ensure proxy/thumbnail for every file in footage/ (e.g. after manual copy)."""
    paths.footage.mkdir(parents=True, exist_ok=True)
    queued: list[str] = []
    for p in list_footage_files(paths.root):
        proxy = proxy_path_for_clip(paths.root, p)
        thumb = thumbnail_path_for_clip(paths.root, p)
        if proxy_is_fresh(p, proxy) and thumbnail_is_fresh(p, thumb):
            continue
        schedule_proxy_work(
            paths.root,
            p,
            ensure_proxy=ensure_proxy,
            ensure_thumbnail=ensure_thumbnail,
            proxy_is_fresh=proxy_is_fresh,
            thumbnail_is_fresh=thumbnail_is_fresh,
            proxy_path_for_clip=proxy_path_for_clip,
            thumbnail_path_for_clip=thumbnail_path_for_clip,
        )
        queued.append(p.name)
        schedule_waveform_work(paths.root, p)
        schedule_index_pipeline(paths.root, p)
    return {"queued": queued}


@app.post("/api/footage/analyze")
def analyze_footage(
    body: FootageAnalyzeBody, paths: ProjectPaths = Depends(get_paths)
) -> dict[str, Any]:
    """Queue transcript + silences + (for video) shots/keyframes + merged index."""
    paths.footage.mkdir(parents=True, exist_ok=True)
    files = list_footage_files(paths.root)
    if body.all:
        targets = files
    elif body.names:
        want = {Path(n).name for n in body.names if n and str(n).strip()}
        by_name = {p.name: p for p in files}
        unknown = sorted(want - set(by_name))
        if unknown:
            raise HTTPException(
                status_code=400,
                detail="These files are not in footage/: " + ", ".join(unknown),
            )
        targets = [by_name[n] for n in sorted(want)]
    else:
        raise HTTPException(status_code=400, detail="Set all=true or provide names")

    for p in targets:
        schedule_index_pipeline(paths.root, p)
    return {"queued": [p.name for p in targets]}


@app.post("/api/footage/{name}/retranscribe")
def retranscribe_footage(name: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    """Re-run transcription with current settings; rebuilds dependent index JSON."""
    base = Path(name).name
    if not base or base != name:
        raise HTTPException(status_code=400, detail="Invalid name")
    clip_path = paths.footage / base
    if not clip_path.is_file():
        raise HTTPException(status_code=404, detail=f"Not in footage/: {base}")
    removed = clear_transcript_dependent_index(paths.root, clip_path)
    schedule_index_pipeline(paths.root, clip_path)
    return {"queued": base, "removed_index_files": removed}


@app.get("/api/storage/stats")
def get_storage_stats(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    return storage_stats(paths.root)


@app.post("/api/storage/clear-regenerable")
def post_clear_regenerable_caches(
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    """Delete perception JPEGs, keyframe images, and local recomputable JSON (not AI captions)."""
    return clear_regenerable_caches(paths.root)


@app.post("/api/storage/clear-paid-captions")
def post_clear_paid_caption_caches(
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    """Delete *_captions.json only; regenerating calls the paid caption API."""
    return clear_paid_caption_caches(paths.root)


@app.get("/api/media/catalog")
def get_media_catalog(
    paths: ProjectPaths = Depends(get_paths),
    scope: str = "all",
    names: str | None = None,
) -> dict[str, Any]:
    """Unified per-file catalog for UI and debugging."""
    only = None
    if names and names.strip():
        only = [n.strip() for n in names.split(",") if n.strip()]
    try:
        entries, warnings = build_media_catalog(
            paths.root,
            scope="selected" if only else "all",
            only_basenames=only,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"entries": entries, "warnings": warnings}


@app.get("/api/media/catalog/detail")
def get_media_catalog_detail(
    name: str,
    start: float | None = None,
    end: float | None = None,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    """Words, shots, and frames for one file. Draft mode does not call this."""
    base = Path(name).name
    if not base or base != name:
        raise HTTPException(status_code=400, detail="Invalid name")
    try:
        entries, _warnings = build_media_catalog(
            paths.root,
            scope="selected",
            only_basenames=[base],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not entries:
        raise HTTPException(status_code=404, detail=f"No catalog entry for {base}")
    from planner_catalog import detail_slice

    return detail_slice(entries[0], start=start, end=end)


def _unanalyzed_names_from_message(msg: str) -> list[str]:
    if "Analyze now:" not in msg:
        return []
    tail = msg.split("Analyze now:", 1)[1]
    return [
        part.strip()
        for part in tail.split(",")
        if part.strip() and part.strip() != "(none)"
    ]


@app.post("/api/planner/estimate")
def estimate_planner(
    body: PlannerEstimateRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    """Token and cost estimate. Does not call the model."""
    with project_cwd(paths):
        try:
            ctx = prepare_planner_context(
                body.brief,
                clip_filenames=body.clip_filenames,
                imitate_style_id=body.imitate_style_id,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "file_count": ctx["file_count"],
        "omitted_count": ctx["omitted"],
        "unanalyzed": ctx["unanalyzed"],
        "input_tokens": ctx["input_tokens"],
        "est_cost_usd": ctx["est_cost_usd"],
        "confirm": ctx["confirm"],
        "model": ctx["model"],
        "catalog_build_ms": ctx["catalog_build_ms"],
        "mode": "draft",
    }


@app.get("/api/footage/{name}/index-job")
def get_index_job_status(name: str) -> dict[str, Any]:
    """Background index pipeline status (transcript → merge)."""
    base = Path(name).name
    if base != name:
        raise HTTPException(status_code=400, detail="Invalid name")
    job = get_index_job(base)
    if job is None:
        return {"status": "idle"}
    return job


@app.delete("/api/footage/{name}")
def delete_footage(name: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    base = Path(name).name
    if base != name or not video_extension_allowed(base):
        raise HTTPException(status_code=400, detail="Invalid footage name")

    clip = paths.footage / base
    if not clip.is_file():
        raise HTTPException(status_code=404, detail="Footage not found")

    rel = f"footage/{base}"
    used_by = plans_referencing_footage(paths.plans, rel)
    if used_by:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Footage is referenced by one or more plans.",
                "plans": used_by,
            },
        )

    try:
        clip.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    proxy = proxy_path_for_clip(paths.root, clip)
    thumb = thumbnail_path_for_clip(paths.root, clip)
    for sidecar in (proxy, thumb):
        if sidecar.is_file():
            try:
                sidecar.unlink()
            except OSError:
                pass

    with project_cwd(paths):
        wf = waveform_path(clip)
        if wf.is_file():
            try:
                wf.unlink()
            except OSError:
                pass

    return {"deleted": base}


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


@app.get("/api/footage/{name}/waveform")
def get_footage_waveform(name: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    """Peak envelope JSON (~100 peaks/sec). Queues background job until cache is ready."""
    base = Path(name).name
    if base != name:
        raise HTTPException(status_code=400, detail="Invalid footage name")
    clip = paths.footage / base
    if not clip.is_file():
        raise HTTPException(status_code=404, detail="Footage not found")

    with project_cwd(paths):
        from index_cache import load_json, waveform_path
        from media import clip_metadata

        wf_job = get_waveform_job(base)
        if wf_job and wf_job.get("status") == "failed":
            return {
                "status": "failed",
                "error": wf_job.get("error"),
            }

        try:
            duration, has_audio, _rotation = clip_metadata(clip)
        except (RuntimeError, OSError):
            raise HTTPException(
                status_code=400, detail="Could not read media metadata"
            ) from None
        if not has_audio:
            return {
                "status": "ready",
                "has_audio": False,
                "duration": round(float(duration), 6),
                "sample_rate_hz_of_peaks": 100.0,
                "peaks": [],
            }

        wpath = waveform_path(clip)
        if wpath.is_file() and wpath.stat().st_mtime >= clip.stat().st_mtime:
            data = load_json(wpath)
            if isinstance(data, dict) and data:
                return {"status": "ready", **data}

        schedule_waveform_work(paths.root, clip)
        return {"status": "processing"}


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
        # Legacy v1 (list or { segments }) — convert in memory so the editor loads;
        # disk is upgraded when the user saves (PUT).
        try:
            data = convert_plan_v1_to_v2(data)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Plan is not schema v2 and could not be auto-converted: {e}",
            ) from e
        with project_cwd(paths):
            errors, warnings = validate_plan_data(data, None)
        if errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "errors": errors,
                    "warnings": warnings,
                    "message": "Converted plan failed validation",
                },
            )
        log_event("info", f"Auto-converted v1 plan to v2 for load: {path.name}")
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
        errors, warnings = validate_plan_data(
            body.timeline, None, project_root=paths.root
        )
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"errors": errors, "warnings": warnings},
        )
    path = paths.plan_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body.timeline, indent=2, ensure_ascii=False) + "\n")
    out: dict[str, Any] = {"saved": path.name}
    if warnings:
        out["warnings"] = warnings
    return out


@app.delete("/api/plans/{name}")
def delete_plan(name: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, str]:
    if any_active_render():
        raise HTTPException(status_code=409, detail="A render is in progress")
    path = paths.plan_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Plan not found")
    try:
        path.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_event("info", f"Deleted plan {path.name}")
    return {"deleted": path.stem}


@app.patch("/api/plans/{name}/rename")
def rename_plan(
    name: str,
    body: PlanRenameBody,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, str]:
    if any_active_render():
        raise HTTPException(status_code=409, detail="A render is in progress")
    src = paths.plan_file(name)
    if not src.is_file():
        raise HTTPException(status_code=404, detail="Plan not found")
    raw = body.to.strip()
    stem = Path(raw).stem
    if not stem or "/" in stem or "\\" in stem:
        raise HTTPException(status_code=400, detail="Invalid target name")
    dst = paths.plan_file(stem)
    if dst.is_file():
        raise HTTPException(status_code=409, detail="Target plan already exists")
    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_event("info", f"Renamed plan {src.name} -> {dst.name}")
    return {"name": dst.stem}


@app.post("/api/plans/{name}/duplicate")
def duplicate_plan(
    name: str,
    body: PlanDuplicateBody,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, str]:
    if any_active_render():
        raise HTTPException(status_code=409, detail="A render is in progress")
    src = paths.plan_file(name)
    if not src.is_file():
        raise HTTPException(status_code=404, detail="Plan not found")
    raw = body.to.strip()
    stem = Path(raw).stem
    if not stem or "/" in stem or "\\" in stem:
        raise HTTPException(status_code=400, detail="Invalid target name")
    dst = paths.plan_file(stem)
    if dst.is_file():
        raise HTTPException(status_code=409, detail="Target plan already exists")
    try:
        shutil.copy2(src, dst)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_event("info", f"Duplicated plan -> {dst.name}")
    return {"name": dst.stem}


@app.post("/api/timeline/apply-op")
def apply_operation(
    body: ApplyOpRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    try:
        with project_cwd(paths):
            result = dispatch_operation(body.timeline, body.operation, body.arguments)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.get("/api/styles")
def list_styles(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    styles_dir = paths.plans / "styles"
    return {"styles": list_style_profiles(styles_dir, paths.root)}


@app.post("/api/styles/analyze")
async def analyze_style(
    request: Request,
    file: UploadFile = File(...),
    style_name: str | None = Form(None),
    style_id: str | None = Form(None),
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    if not _client_host_allowed(request):
        raise HTTPException(status_code=403, detail="Localhost only")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    try:
        base = sanitize_upload_basename(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    ref_dir = paths.root / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    dest = ref_dir / base
    if dest.is_file():
        stem = dest.stem
        ext = dest.suffix
        n = 2
        while n < 10000:
            candidate = ref_dir / f"{stem}_{n}{ext}"
            if not candidate.is_file():
                dest = candidate
                break
            n += 1
        else:
            raise HTTPException(status_code=409, detail="Could not pick a free reference name")

    try:
        data = await file.read()
        dest.write_bytes(data)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        ffprobe_validate_video(dest)
    except RuntimeError as e:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=str(e)) from e

    display_name = (style_name or "").strip() or dest.stem
    sid = slug_style_id(style_id.strip() if style_id else None, fallback=dest.stem)
    api_key = effective_planner_api_key(paths.root)
    with project_cwd(paths):
        try:
            profile = analyze_reference_video(
                dest,
                style_id=sid,
                style_name=display_name,
                api_key=api_key,
            )
        except ValueError as e:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=500, detail=str(e)) from e

    sid = str(profile.get("style_id") or sid)
    out_path = paths.plans / "styles" / f"{sid}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_event("info", f"Style profile saved: {out_path.name}")
    rel = f"references/{dest.name}"
    return {
        "style_id": sid,
        "style_name": profile.get("style_name") or display_name,
        "file": rel,
        "profile_path": f"plans/styles/{sid}.json",
        "profile": profile,
    }


@app.post("/api/planner/run")
def run_planner(
    body: PlannerRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    mode = (body.mode or "draft").strip().lower()
    if mode != "draft":
        raise HTTPException(
            status_code=400,
            detail=(
                "Full mode is not available yet. Use Draft. "
                "The agent loop is a later step."
            ),
        )
    api_key = effective_planner_api_key(paths.root)
    with project_cwd(paths):
        try:
            plan_v2, group_id, usage = generate_plan(
                body.brief,
                api_key=api_key,
                clip_filenames=body.clip_filenames,
                imitate_style_id=body.imitate_style_id,
                require_merged_index=False,
                mode=mode,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            msg = str(e)
            if "Analyze now" in msg or "No analyzed media" in msg:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": msg,
                        "unanalyzed": _unanalyzed_names_from_message(msg),
                        "hint": "POST /api/footage/analyze with { names: [...] }",
                    },
                ) from e
            if msg.startswith("Planner stopped") or msg.startswith("Full mode"):
                raise HTTPException(status_code=400, detail=msg) from e
            raise HTTPException(status_code=503, detail=msg) from e
        except ValueError as e:
            detail = e.args[0] if e.args and isinstance(e.args[0], list) else str(e)
            raise HTTPException(status_code=400, detail=detail)

    path = paths.plan_file(body.save_as)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan_v2, indent=2, ensure_ascii=False) + "\n")
    log_event("info", f"Planner wrote {path.name}")
    with project_cwd(paths):
        from audio_cut_refine import check_word_clipped_at_cuts

        cut_warnings = check_word_clipped_at_cuts(plan_v2, root=paths.root)
    return {
        "plan_name": path.name,
        "group_id": group_id,
        "usage": usage,
        "timeline": plan_v2,
        "cut_quality_warnings": cut_warnings,
    }


def _run_render_job(
    job_id: str,
    paths: ProjectPaths,
    body: RenderRequest,
    out_path: Path,
) -> None:
    on_prog = bind_progress(job_id)
    cancel_ev = get_cancel_event(job_id)

    def tick(pct: float | None) -> None:
        on_prog(pct, "")

    try:
        update_job(job_id, state="running", percent=0.0)
        with project_cwd(paths):
            defaults = effective_render_defaults(paths.root)
            caps = body.captions if body.captions is not None else bool(
                defaults.get("captions", False)
            )
            max_len = (
                body.max_length
                if body.max_length is not None
                else defaults.get("max_length")
            )
            crf = body.video_crf
            if crf is None and defaults.get("video_crf") is not None:
                try:
                    crf = int(defaults["video_crf"])
                except (TypeError, ValueError):
                    crf = None
            if body.timeline is not None:
                plan_path = None
                if caps and body.plan_name:
                    plan_path = paths.plan_file(body.plan_name)
                render_plan_data(
                    body.timeline,
                    out_path,
                    root=paths.root,
                    captions=caps,
                    max_length=max_len,
                    plan_path_for_captions=plan_path,
                    cancel_event=cancel_ev,
                    on_timeline_progress=tick,
                    video_crf=crf,
                )
            else:
                assert body.plan_name
                render_plan_file(
                    paths.plan_file(body.plan_name),
                    out_path,
                    root=paths.root,
                    captions=caps,
                    max_length=max_len,
                    cancel_event=cancel_ev,
                    on_timeline_progress=tick,
                    video_crf=crf,
                )
    except RuntimeError as e:
        err = str(e)
        if "cancelled" in err.lower():
            update_job(job_id, state="cancelled", error=None, percent=None)
            if out_path.is_file():
                try:
                    out_path.unlink()
                except OSError:
                    pass
            log_event("info", f"Render job {job_id} cancelled")
            return
        update_job(job_id, state="failed", error=err, percent=None, log_append=err + "\n")
        log_event("error", f"Render job {job_id} failed: {err[:500]}")
        return
    except FileNotFoundError as e:
        update_job(job_id, state="failed", error=str(e))
        return
    except ValueError as e:
        detail = e.args[0] if e.args and isinstance(e.args[0], list) else str(e)
        err = str(detail)
        update_job(job_id, state="failed", error=err)
        return

    rel = str(out_path.relative_to(paths.root))
    url = f"/api/output/{out_path.name}"
    update_job(
        job_id,
        state="done",
        percent=100.0,
        output=rel,
        url=url,
    )
    log_event("info", f"Render job {job_id} done -> {out_path.name}")


@app.post("/api/render")
def start_render(
    body: RenderRequest,
    paths: ProjectPaths = Depends(get_paths),
) -> dict[str, Any]:
    if not body.plan_name and not body.timeline:
        raise HTTPException(status_code=400, detail="Provide plan_name or timeline")

    out_path = paths.output_file(body.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    job_id, _ = create_job()
    update_job(job_id, state="queued")

    def runner() -> None:
        _run_render_job(job_id, paths, body, out_path)

    threading.Thread(target=runner, name=f"render-{job_id}", daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/render/{job_id}")
def render_status(job_id: str) -> dict[str, Any]:
    pub = get_job_public(job_id)
    if not pub:
        raise HTTPException(status_code=404, detail="Job not found")
    return pub


@app.post("/api/render/{job_id}/cancel")
def cancel_render(job_id: str) -> dict[str, str]:
    ok = request_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    log_event("info", f"Cancel requested for render {job_id}")
    return {"ok": "true"}


@app.get("/api/output")
def list_output_files(paths: ProjectPaths = Depends(get_paths)) -> dict[str, Any]:
    paths.output.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for p in sorted(paths.output.iterdir()):
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        files.append(
            {
                "name": p.name,
                "size_bytes": st.st_size,
                "download_url": f"/api/output/{p.name}",
            }
        )
    return {"files": files}


@app.delete("/api/output/{name}")
def delete_output(name: str, paths: ProjectPaths = Depends(get_paths)) -> dict[str, str]:
    base = Path(name).name
    if base != name:
        raise HTTPException(status_code=400, detail="Invalid name")
    path = paths.output / base
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")
    try:
        path.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_event("info", f"Deleted output {base}")
    return {"deleted": base}


@app.post("/api/desktop/reveal-output")
def reveal_output_folder(request: Request, paths: ProjectPaths = Depends(get_paths)) -> dict[str, str]:
    if not _client_host_allowed(request):
        raise HTTPException(status_code=403, detail="Localhost only")
    paths.output.mkdir(parents=True, exist_ok=True)
    target = str(paths.output.resolve())
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log_event("info", "Opened output folder via desktop API")
    return {"opened": target}


@app.get("/api/output/{name}")
def serve_output(name: str, paths: ProjectPaths = Depends(get_paths)) -> FileResponse:
    base = Path(name).name
    path = paths.output / base
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")
    return FileResponse(path, media_type="video/mp4", filename=base)


__all__ = ["app", "set_paths"]
