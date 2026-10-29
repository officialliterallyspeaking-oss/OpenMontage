"""OpenMontage Studio — FastAPI app.

Serves the single-page UI and a small JSON API. All generation work is
delegated to the repository's own tools (see ``studio/pipelines.py``).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from studio import jobs as store
from studio import pipelines
from studio.repo_bridge import (
    PROJECTS_DIR,
    REPO_ROOT,
    catalog,
    ffmpeg_status,
    masked_keys,
    provider_choices,
    reload_registry,
    save_keys,
)
from studio.motion import ASPECTS, MOTION_PRESETS

UI_DIR = Path(__file__).resolve().parent / "ui"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "studio_state" / "uploads"
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
BACKLOT_PORT = 4750


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------

class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    aspect: str = "16:9"
    style: str = "clean-professional"
    provider: str = "auto"
    count: int = Field(default=1, ge=1, le=4)
    allow_placeholder: bool = True


class VideoFromTextRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    aspect: str = "16:9"
    style: str = "clean-professional"
    provider: str = "auto"
    duration_seconds: float = Field(default=6.0, ge=2, le=20)
    motion: str = "ken_burns"
    engine: str = "motion"  # motion | video_model
    count: int = Field(default=1, ge=1, le=4)
    allow_placeholder: bool = True


class KeyRequest(BaseModel):
    keys: dict[str, str]


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenMontage Studio", version="1.0.0", docs_url="/api/docs")

if UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = UI_DIR / "index.html"
    if not page.exists():  # pragma: no cover
        return HTMLResponse("<h1>Studio UI missing</h1>", status_code=500)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "openmontage-studio",
        "repo": str(REPO_ROOT),
        "jobs": store.stats(),
        "ffmpeg": ffmpeg_status(),
    }


@app.get("/api/presets")
def presets() -> dict[str, Any]:
    styles = []
    styles_dir = REPO_ROOT / "styles"
    if styles_dir.is_dir():
        for path in sorted(styles_dir.glob("*.yaml")):
            styles.append(
                {
                    "id": path.stem,
                    "label": path.stem.replace("-", " ").title(),
                    "accent": _style_accent(path),
                }
            )
    return {
        "aspects": [{"id": k, "label": k, "px": v} for k, v in ASPECTS.items()],
        "motions": [{"id": k, "label": v} for k, v in MOTION_PRESETS.items()],
        "styles": styles,
    }


def _style_accent(path: Path) -> str:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        palette = data.get("chart_palette") or []
        if palette:
            return str(palette[0])
    except Exception:
        pass
    return "#2563EB"


@app.get("/api/catalog")
def get_catalog() -> dict[str, Any]:
    data = catalog()
    data["providers"] = {
        "image_generation": provider_choices("image_generation"),
        "video_generation": provider_choices("video_generation"),
        "tts": provider_choices("tts"),
    }
    return data


@app.get("/api/keys")
def get_keys() -> dict[str, Any]:
    return {"keys": masked_keys(), "configured": sorted(catalog()["env"]["configured"])}


@app.post("/api/keys")
def post_keys(request: KeyRequest) -> dict[str, Any]:
    if not request.keys:
        raise HTTPException(400, "no keys supplied")
    result = save_keys(request.keys)
    reload_registry()
    result["providers"] = {
        "image_generation": provider_choices("image_generation"),
        "video_generation": provider_choices("video_generation"),
    }
    return result


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in store.all_jobs()], "stats": store.stats()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job.to_dict()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, Any]:
    return {"deleted": store.delete(job_id)}


@app.post("/api/images")
def create_image(request: ImageRequest) -> dict[str, Any]:
    if request.aspect not in ASPECTS:
        raise HTTPException(400, f"unsupported aspect: {request.aspect}")
    job = pipelines.start(
        "image",
        request.prompt,
        aspect=request.aspect,
        style=request.style,
        provider=request.provider,
        count=request.count,
        allow_placeholder=request.allow_placeholder,
    )
    return job.to_dict()


@app.post("/api/videos/from-text")
def create_video_from_text(request: VideoFromTextRequest) -> dict[str, Any]:
    if request.aspect not in ASPECTS:
        raise HTTPException(400, f"unsupported aspect: {request.aspect}")
    if request.motion not in MOTION_PRESETS:
        raise HTTPException(400, f"unknown motion preset: {request.motion}")
    job = pipelines.start(
        "video_from_text",
        request.prompt,
        aspect=request.aspect,
        style=request.style,
        provider=request.provider,
        duration_seconds=request.duration_seconds,
        motion=request.motion,
        engine=request.engine,
        count=request.count,
        allow_placeholder=request.allow_placeholder,
    )
    return job.to_dict()


@app.post("/api/videos/from-image")
async def create_video_from_image(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    aspect: str = Form("16:9"),
    style: str = Form("clean-professional"),
    provider: str = Form("auto"),
    duration_seconds: float = Form(6.0),
    motion: str = Form("ken_burns"),
    engine: str = Form("motion"),
) -> dict[str, Any]:
    if aspect not in ASPECTS:
        raise HTTPException(400, f"unsupported aspect: {aspect}")
    if motion not in MOTION_PRESETS:
        raise HTTPException(400, f"unknown motion preset: {motion}")
    if not (2 <= duration_seconds <= 20):
        raise HTTPException(400, "duration must be between 2 and 20 seconds")

    suffix = Path(file.filename or "upload.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        raise HTTPException(400, "unsupported image type")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time() * 1000)}-{file.filename or 'upload'}"
    safe_name = "".join(c for c in stamp if c.isalnum() or c in "-_. ").strip()
    target = UPLOAD_DIR / safe_name

    size = 0
    with open(target, "wb") as handle:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "image is larger than 32 MB")
            handle.write(chunk)

    try:  # the file must actually decode as an image
        from PIL import Image

        with Image.open(target) as img:
            img.verify()
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "file is not a readable image")

    job = pipelines.start(
        "video_from_image",
        prompt or "cinematic camera move",
        upload_path=target,
        aspect=aspect,
        style=style,
        provider=provider,
        duration_seconds=float(duration_seconds),
        motion=motion,
        engine=engine,
        source_upload=str(target),
    )
    return job.to_dict()


# ---------------------------------------------------------------------------
# media (project files only)
# ---------------------------------------------------------------------------

@app.get("/media/projects/{file_path:path}")
def media(file_path: str):
    root = PROJECTS_DIR.resolve()
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)


@app.get("/media/uploads/{file_path:path}")
def media_uploads(file_path: str):
    root = UPLOAD_DIR.resolve()
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)


# ---------------------------------------------------------------------------
# Backlot (the repo's own live board)
# ---------------------------------------------------------------------------

def _board_alive() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{BACKLOT_PORT}/api/health", timeout=1.2
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


@app.get("/api/board/status")
def board_status() -> dict[str, Any]:
    return {
        "alive": _board_alive(),
        "port": BACKLOT_PORT,
        "url": f"/board",
        "direct_url": f"http://127.0.0.1:{BACKLOT_PORT}/",
    }


@app.post("/api/board/open")
def board_open() -> dict[str, Any]:
    if _board_alive():
        return {"alive": True, "url": "/board"}
    try:
        env = {
            **os.environ,
            "BACKLOT_PORT": str(BACKLOT_PORT),
            "BACKLOT_HOST": "0.0.0.0",
        }
        subprocess.Popen(
            [sys.executable, "-m", "studio.board_host"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        raise HTTPException(500, f"could not start the board: {exc}")
    for _ in range(40):
        if _board_alive():
            return {"alive": True, "url": "/board"}
        time.sleep(0.25)
    raise HTTPException(504, "the board did not start in time")


def _board_origin(request: Request) -> str:
    """Board URL reachable from the caller.

    Direct desktop use is 127.0.0.1:4750. Behind a port-forwarding preview the
    Studio is served on ``<port>-<host>``, so the board is another port on the
    same host — hence the port swap.
    """
    host = request.headers.get("host", "")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    match = re.match(r"^(\d+)-(.+)$", host.split(":")[0])
    if match:
        return f"{scheme}://{BACKLOT_PORT}-{match.group(2)}"
    return f"http://127.0.0.1:{BACKLOT_PORT}"


@app.get("/api/board/url")
def board_url(request: Request) -> dict[str, Any]:
    return {"alive": _board_alive(), "url": _board_origin(request)}


@app.get("/board")
def board_redirect(request: Request):
    if not _board_alive():
        return HTMLResponse(
            "<!doctype html><body style='font:16px system-ui;background:#0b0d12;color:#e5e7eb;"
            "padding:48px'><h2 style='color:#fff'>The Backlot board isn't running yet</h2>"
            "<p>Use the <b>Open board</b> button in the Studio header, or run:</p>"
            "<pre style='background:#11151d;padding:16px;border-radius:8px'>"
            "python -m backlot serve --port 4750</pre>"
            "<p style='color:#9aa4b2'>The board is the repository's own live storyboard — "
            "it reads the same project files this Studio writes.</p></body>",
            status_code=200,
        )
    return RedirectResponse(f"{_board_origin(request)}/", status_code=307)


def create_app() -> FastAPI:
    return app


__all__ = ["app", "create_app"]
