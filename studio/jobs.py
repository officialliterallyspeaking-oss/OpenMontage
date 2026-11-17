"""Job model + persistence for Studio requests.

A "job" is one user action (an image, or a video from a prompt/image). Jobs are
kept in memory for the running process and mirrored to
``studio_state/jobs.json`` so the gallery survives a reload/restart. Large media
never goes in that file — only paths under ``projects/``.

Every job also gets a real OpenMontage project workspace
(``projects/studio-<slug>-<id>/``) written through ``lib.checkpoint.init_project``
and ``lib.events.emit_event``, so the Backlot board can watch the run and the
existing repo conventions (workspace layout, event stream) hold.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from studio.repo_bridge import PROJECTS_DIR, REPO_ROOT

STATE_DIR = REPO_ROOT / "studio_state"
JOBS_PATH = STATE_DIR / "jobs.json"
MAX_JOBS = 200

_lock = threading.RLock()
_jobs: dict[str, "Job"] = {}
_order: list[str] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, limit: int = 42) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:limit].strip("-")) or "untitled"


@dataclass
class Step:
    name: str
    status: str = "pending"  # pending | running | done | failed | skipped
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Job:
    id: str
    kind: str  # image | video_from_text | video_from_image
    prompt: str
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    status: str = "queued"  # queued | running | done | failed
    provider: str = "auto"
    engine: str = "motion"  # motion | video_model
    style: str = "clean-professional"
    aspect: str = "16:9"
    duration_seconds: float = 6.0
    motion: str = "ken_burns"
    count: int = 1
    allow_placeholder: bool = True
    project_id: str = ""
    project_dir: str = ""
    placeholder: bool = False
    provider_announcement: dict[str, Any] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    video: Optional[dict[str, Any]] = None
    log: list[str] = field(default_factory=list)
    error: Optional[str] = None
    cost_usd: float = 0.0
    source_upload: Optional[str] = None

    # -- mutators -----------------------------------------------------------
    def touch(self) -> None:
        self.updated_at = _now()

    def note(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")
        self.touch()

    def step(self, name: str, status: str, detail: str = "") -> None:
        for item in self.steps:
            if item.name == name:
                item.status, item.detail = status, detail or item.detail
                break
        else:
            self.steps.append(Step(name, status, detail))
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [asdict(s) for s in self.steps]
        data["backlot_url"] = "/board"
        return data


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def save() -> None:
    with _lock:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "jobs": [j.to_dict() for j in _jobs.values()]}
        tmp = JOBS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(JOBS_PATH)


def load() -> None:
    """Rehydrate the gallery, reconciling runs the last process left behind.

    Studio is deliberately single-process: jobs live in memory and are mirrored
    here. So a job persisted as ``queued``/``running`` cannot still be working —
    the process that owned it is gone. Left alone it would sit in the gallery
    forever and the UI would keep polling a run that will never advance. Mark
    those ``failed`` with an explicit reason instead.
    """
    if not JOBS_PATH.exists():
        return
    try:
        payload = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return

    reconciled = 0
    with _lock:
        for raw in payload.get("jobs", []):
            try:
                steps = [Step(**s) for s in raw.pop("steps", [])]
                raw.pop("backlot_url", None)
                job = Job(**raw)
                job.steps = steps
                _jobs[job.id] = job
                _order.append(job.id)
            except Exception:
                continue

            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = (
                    "Interrupted: the Studio server restarted while this run was "
                    "in progress. Submit it again to regenerate."
                )
                for step in job.steps:
                    if step.status in ("pending", "running"):
                        step.status = "failed"
                        step.detail = step.detail or "interrupted"
                job.note("Marked interrupted on server restart.")
                reconciled += 1

    if reconciled:
        save()


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------

def create(kind: str, prompt: str, **kwargs: Any) -> Job:
    job_id = uuid.uuid4().hex[:10]
    clean_prompt = (prompt or "").strip()
    project_id = f"studio-{slugify(clean_prompt)}-{job_id[:6]}"
    project_dir = PROJECTS_DIR / project_id

    job = Job(id=job_id, kind=kind, prompt=clean_prompt, **kwargs)
    job.project_id = project_id
    job.project_dir = str(project_dir)

    with _lock:
        _jobs[job_id] = job
        _order.append(job_id)
        if len(_order) > MAX_JOBS:
            for stale in _order[:-MAX_JOBS]:
                _jobs.pop(stale, None)
            del _order[:-MAX_JOBS]
    save()
    return job


def get(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def all_jobs() -> list[Job]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


def delete(job_id: str) -> bool:
    """Remove a job from the gallery (leaves the project files on disk)."""
    with _lock:
        if job_id not in _jobs:
            return False
        _jobs.pop(job_id, None)
        if job_id in _order:
            _order.remove(job_id)
    save()
    return True


def stats() -> dict[str, Any]:
    jobs = all_jobs()
    return {
        "total": len(jobs),
        "done": sum(1 for j in jobs if j.status == "done"),
        "running": sum(1 for j in jobs if j.status in ("queued", "running")),
        "failed": sum(1 for j in jobs if j.status == "failed"),
        "images": sum(len(j.assets) for j in jobs),
        "videos": sum(1 for j in jobs if j.video),
        "cost_usd": round(sum(j.cost_usd or 0 for j in jobs), 4),
    }


def wait_until(job_id: str, timeout: float = 300.0) -> Optional[Job]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get(job_id)
        if job and job.status in ("done", "failed"):
            return job
        time.sleep(0.15)
    return get(job_id)


load()
