"""Studio project API — the four systems exposed as one creative workflow.

Routes are grouped:

    /api/studio/capabilities      what the studio can do right now, honestly
    /api/studio/upload            bring an image in
    /api/studio/projects          create / list campaigns
    /api/studio/projects/{id}     the whole project state (shared memory)
    .../refine                    Creative Control: change one thing
    .../retry                     resume after a failure, keeping finished work
    .../media/{file}              rendered files
    .../artifacts/{file}          schema-shaped artifacts for inspection

Every response carries provenance. Nothing here reports a step as finished
before the component that produces it actually has data.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from studio.brain import creative
from studio.brain.orchestrator import ORCHESTRATOR, Orchestrator
from studio.brain.projects import STORE, Project, ProjectStore

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "studio_state" / "uploads"
MAX_UPLOAD_BYTES = 32 * 1024 * 1024

router = APIRouter(prefix="/api/studio", tags=["studio-projects"])

# One render at a time keeps the CPU predictable on a sandbox machine; the
# queue is still fair because each project keeps its own progress.
_render_slot = threading.BoundedSemaphore(2)
_lock = threading.RLock()
_running: dict[str, threading.Thread] = {}


class CreateRequest(BaseModel):
    mode: str = "text"  # image | text | tiktok
    text: str = Field(default="", max_length=4000)
    upload_id: str = ""
    platform: str = ""
    duration_seconds: Optional[float] = None
    provider: str = "auto"
    aspect: str = ""
    advance: dict[str, Any] = Field(default_factory=dict)


class RefineRequest(BaseModel):
    operation: str
    payload: dict[str, Any] = Field(default_factory=dict)


def _store() -> ProjectStore:
    return STORE


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------

@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    """What can actually happen here, with the reason for each answer."""
    image = creative.choose_image_model()
    video = creative.choose_video_model(needs_motion=True, image_reference=True, seconds=8)
    return {
        "image": {
            "available": image["available"],
            "chosen": (image["chosen"] or {}).get("name"),
            "considered": image.get("considered"),
            "reason": image["reason"],
        },
        "video": {
            "available": video["available"],
            "chosen": (video["chosen"] or {}).get("name"),
            "considered": video.get("considered"),
            "reason": video["reason"],
        },
        "local_mode": {
            "available": True,
            "what_it_means": (
                "Frames are composed by the studio's art director and framed as local "
                "previews. The script, storyboard, timing, captions, QA and publishing "
                "package are genuine either way."
            ),
        },
        "audio": {
            "available": False,
            "reason": "No voice or music provider is configured; exports are silent and "
                      "the package tells you to add the trending sound in the app.",
        },
        "posting": {
            "available": False,
            "reason": "The studio never posts on your behalf. It exports and prepares.",
        },
    }


# ---------------------------------------------------------------------------
# uploads
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "upload.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        raise HTTPException(400, "unsupported image type")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time() * 1000)}-{Path(file.filename or 'upload').stem[:40]}"
    safe = "".join(c for c in stamp if c.isalnum() or c in "-_ ").strip() + suffix
    target = UPLOAD_DIR / safe

    size = 0
    with open(target, "wb") as handle:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "image is larger than 32 MB")
            handle.write(chunk)

    try:
        from PIL import Image

        with Image.open(target) as img:
            img.verify()
            width, height = img.size
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "file is not a readable image")

    return {
        "upload_id": target.name,
        "filename": file.filename,
        "bytes": size,
        "width": width,
        "height": height,
        "url": f"/media/uploads/{target.name}",
    }


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

def _upload_path(upload_id: str) -> Optional[str]:
    if not upload_id:
        return None
    candidate = (UPLOAD_DIR / Path(upload_id).name).resolve()
    if not str(candidate).startswith(str(UPLOAD_DIR.resolve())) or not candidate.is_file():
        raise HTTPException(400, "unknown upload")
    return str(candidate)


def _start(project: Project) -> None:
    def work() -> None:
        with _render_slot:
            orchestrator = Orchestrator(_store())
            orchestrator.run(project)
        with _lock:
            _running.pop(project.id, None)

    thread = threading.Thread(target=work, name=f"studio-{project.id}", daemon=True)
    with _lock:
        _running[project.id] = thread
    thread.start()


@router.post("/projects")
def create_project(request: CreateRequest) -> dict[str, Any]:
    text = (request.text or "").strip()
    upload = _upload_path(request.upload_id)
    if request.mode == "image" and not upload:
        raise HTTPException(400, "Create from Image needs an uploaded image")
    if not text and not upload:
        raise HTTPException(400, "give the studio at least a sentence or an image")

    payload: dict[str, Any] = {
        "mode": request.mode,
        "text": text,
        "upload_path": upload,
        "provider": request.provider,
    }
    if request.platform:
        payload["platform"] = request.platform
    if request.aspect:
        payload["aspect"] = request.aspect
    if request.duration_seconds:
        payload["duration_seconds"] = float(request.duration_seconds)
    if request.mode == "tiktok":
        payload.setdefault("platform", "tiktok")
    if request.advance:
        payload["advance"] = request.advance

    project = _store().create(payload, title=text[:80] or "Uploaded image campaign")
    project.event("studio", f"Project created from {request.mode} start point")
    _store().save(project)
    _start(project)
    return project.public()


@router.get("/projects")
def list_projects() -> dict[str, Any]:
    projects = _store().list()
    return {"projects": projects, "count": len(projects)}


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    payload = project.public()
    payload["running"] = project_id in _running
    payload["refinements"] = ORCHESTRATOR.REFINEMENTS
    return payload


@router.post("/projects/{project_id}/refine")
def refine_project(project_id: str, request: RefineRequest) -> dict[str, Any]:
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if project.status == "running":
        raise HTTPException(409, "this project is still working — wait for it to finish")
    orchestrator = Orchestrator(_store())
    if request.operation not in orchestrator.REFINEMENTS:
        raise HTTPException(400, f"unknown refinement '{request.operation}'")
    preview = orchestrator.preview(project, request.operation)

    def work() -> None:
        with _render_slot:
            try:
                orchestrator.refine(project, request.operation, request.payload)
            except ValueError as exc:
                project.status = "complete"
                project.error = str(exc)
                _store().save(project)
            finally:
                with _lock:
                    _running.pop(project.id, None)

    thread = threading.Thread(target=work, name=f"studio-refine-{project_id}", daemon=True)
    with _lock:
        _running[project_id] = thread
    thread.start()
    return {
        "project": project.public(),
        "operation": request.operation,
        "recomputing": preview,
        "label": orchestrator.REFINEMENTS[request.operation]["label"],
    }


@router.post("/projects/{project_id}/retry")
def retry_project(project_id: str) -> dict[str, Any]:
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if project_id in _running:
        raise HTTPException(409, "already running")
    project.status = "running"
    project.error = None
    project.event("studio", "Retrying — finished steps are kept")
    _store().save(project)
    _start(project)
    return {"project": project.public(), "kept": [
        name for name in project.components if project.components[name].done
    ]}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    import shutil

    removed = _store().delete(project_id)
    directory = _store().dir_for(project_id)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
    return {"deleted": removed, "id": project_id}


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------

def _safe(project: Project, relative: str) -> Path:
    root = _store().dir_for(project.id).resolve()
    target = (root / relative).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "not found")
    return target


@router.get("/projects/{project_id}/media/{filename}")
def project_media(project_id: str, filename: str):
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    for candidate in (f"renders/{filename}", f"assets/frames/{filename}"):
        try:
            return FileResponse(_safe(project, candidate))
        except HTTPException:
            continue
    raise HTTPException(404, "not found")


@router.get("/projects/{project_id}/artifacts/{filename}")
def project_artifact(project_id: str, filename: str):
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return FileResponse(_safe(project, f"artifacts/{Path(filename).name}"))


# ---------------------------------------------------------------------------
# advanced studio
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/inspect")
def inspect_project(project_id: str) -> dict[str, Any]:
    """Everything Advanced Studio needs, in one call."""
    project = _store().get(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return {
        "prompts": project.get("prompts"),
        "visual_plan": project.get("visual_plan"),
        "storyboard": project.get("storyboard"),
        "edit": project.get("edit"),
        "cues": project.get("cues"),
        "concept": project.get("concept"),
        "assets": project.get("assets"),
        "artifacts": sorted(
            p.name for p in (_store().dir_for(project_id) / "artifacts").glob("*.json")
        ),
    }
