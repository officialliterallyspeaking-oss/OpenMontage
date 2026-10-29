"""Shared creative context and project memory.

Every system reads from and writes to one `Project`. That object is the reason
the TikTok caption can describe the video that actually exists instead of a
different story: the growth engine reads ``script``/``storyboard``/``render``,
not the user's original prompt.

Components are tracked individually (``stamp`` + ``deps``) so a refinement can
recompute exactly what it invalidates. Changing the music must not re-run the
director or the SEO; changing the concept must.

On disk: ``projects/<id>/brain/context.json`` — human readable, diffable, and
next to the standard OpenMontage artifacts and checkpoints for the same project.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = REPO_ROOT / "projects"

# Component order matters: later components depend on earlier ones.
COMPONENTS = [
    "intent",       # what the user actually asked for
    "media",        # analysis of uploaded images
    "concept",      # director: options + selection + rationale
    "brief",        # director: the creative brief
    "hooks",        # director: scored hook options
    "beats",        # director: the beat sheet the rest of the piece follows
    "visual_plan",  # creative engine: shot/motion/palette plan
    "prompts",      # creative engine: model-ready prompts
    "assets",       # creative engine: generated (or derived) stills
    "script",       # producer: narration script
    "storyboard",   # producer: scene-by-scene plan
    "scene_assets",  # runtime link from scene id -> rendered file
    "edit",         # producer: timeline decisions
    "cues",         # producer: caption cues tied to scenes
    "render",       # producer: assembled video
    "review",       # producer: review findings
    "final_review", # producer: technical + honesty checks
    "seo",          # growth engine: publishing package
]

DEFAULT_DEPS: dict[str, list[str]] = {
    "intent": [],
    "media": [],
    "concept": ["intent", "media"],
    "brief": ["concept", "intent"],
    "hooks": ["concept"],
    "beats": ["concept", "intent"],
    # the visual plan derives from the concept and the measured source, not from
    # copy — that is what lets a hook rewrite skip re-rendering the artwork
    "visual_plan": ["concept", "beats", "media"],
    "prompts": ["visual_plan"],
    "assets": ["prompts", "visual_plan"],
    "script": ["brief", "concept", "beats"],
    "storyboard": ["script", "visual_plan", "assets"],
    "scene_assets": ["assets", "storyboard"],
    "edit": ["storyboard", "scene_assets"],
    "cues": ["script", "storyboard"],
    "render": ["edit", "cues", "storyboard", "scene_assets"],
    "review": ["render"],
    "final_review": ["render", "assets"],
    "seo": ["brief", "concept", "script", "storyboard", "render", "final_review"],
}

# The six progress stages the user sees. Each maps to real component changes.
USER_STAGES = [
    ("understand", "Understanding your idea"),
    ("concept", "Developing the creative concept"),
    ("assets", "Creating your visual assets"),
    ("produce", "Producing your content"),
    ("check", "Checking the final result"),
    ("publish", "Preparing your TikTok post"),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text: str, limit: int = 40) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return (value[:limit].strip("-")) or "project"


def _hash(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


@dataclass
class Component:
    name: str
    data: Any = None
    stamp: str = ""
    updated_at: str = ""
    deps: list[str] = field(default_factory=lambda: [])
    seconds: float = 0.0

    @property
    def done(self) -> bool:
        return bool(self.stamp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "done": self.done,
            "stamp": self.stamp,
            "updated_at": self.updated_at,
            "seconds": round(self.seconds, 2),
            "deps": self.deps,
        }


@dataclass
class Project:
    id: str
    title: str
    request: dict[str, Any]
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    status: str = "created"          # created | running | complete | failed
    stage: str = ""                  # current user-facing stage key
    components: dict[str, Component] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    versions: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    pipeline: str = "tiktok-studio"

    def __post_init__(self) -> None:
        for name in COMPONENTS:
            self.components.setdefault(
                name, Component(name=name, deps=list(DEFAULT_DEPS.get(name, [])))
            )

    def mark(self, name: str, seconds: float) -> None:
        comp = self.components.get(name)
        if comp is not None:
            comp.seconds = round(float(seconds), 2)

    # -- component access ---------------------------------------------------
    def put(self, name: str, data: Any, *, seconds: float = 0.0) -> None:
        comp = self.components.setdefault(name, Component(name=name))
        comp.data = data
        comp.stamp = _hash(data)
        comp.updated_at = now()
        comp.seconds = round(seconds, 2)
        self.updated_at = now()

    def get(self, name: str, default: Any = None) -> Any:
        comp = self.components.get(name)
        return comp.data if comp and comp.done else default

    def has(self, name: str) -> bool:
        comp = self.components.get(name)
        return bool(comp and comp.done)

    def missing(self, names: list[str]) -> list[str]:
        return [n for n in names if not self.has(n)]

    def invalidate(self, names: list[str], *, cascade: bool = True,
                   keep_data: tuple[str, ...] = ()) -> list[str]:
        """Clear components and (optionally) everything downstream of them.

        ``keep_data`` clears the *stamp* (so the step re-runs) but leaves the
        payload in place — used for assets, where the next run wants the old
        frames available for per-shot reuse.
        """
        targets = set(names)
        if cascade:
            changed = True
            while changed:
                changed = False
                for name in COMPONENTS:
                    comp = self.components[name]
                    if name in targets or not comp.done:
                        continue
                    if any(dep in targets for dep in comp.deps):
                        targets.add(name)
                        changed = True
        dropped = []
        for name in targets:
            comp = self.components.get(name)
            if comp and comp.done:
                if name not in keep_data:
                    comp.data = None
                comp.stamp = ""
                comp.updated_at = ""
                dropped.append(name)
        return dropped

    # -- events -------------------------------------------------------------
    def event(self, system: str, message: str, **extra: Any) -> dict[str, Any]:
        record = {
            "at": now(),
            "t": round(time.time(), 3),
            "system": system,
            "message": message,
            **extra,
        }
        self.events.append(record)
        self.updated_at = now()
        return record

    def snapshot(self, label: str) -> None:
        counts = {k: self.has(k) for k in COMPONENTS}
        self.versions.append({"label": label, "at": now(), "components": counts})

    # -- persistence --------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "2.0",
            "id": self.id,
            "title": self.title,
            "pipeline": self.pipeline,
            "status": self.status,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "request": self.request,
            "components": {
                name: {**comp.to_dict(), "data": comp.data}
                for name, comp in self.components.items()
            },
            "events": self.events[-400:],
            "versions": self.versions[-40:],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Project":
        project = cls(
            id=raw["id"],
            title=raw.get("title", ""),
            request=raw.get("request", {}),
            created_at=raw.get("created_at", now()),
            updated_at=raw.get("updated_at", now()),
            status=raw.get("status", "created"),
            stage=raw.get("stage", ""),
            error=raw.get("error"),
            pipeline=raw.get("pipeline", "tiktok-studio"),
        )
        for name, payload in (raw.get("components") or {}).items():
            if name not in COMPONENTS:
                continue
            project.components[name] = Component(
                name=name,
                data=payload.get("data"),
                stamp=payload.get("stamp", ""),
                updated_at=payload.get("updated_at", ""),
                deps=payload.get("deps") or list(DEFAULT_DEPS.get(name, [])),
                seconds=payload.get("seconds", 0.0) or 0.0,
            )
        project.events = raw.get("events") or []
        project.versions = raw.get("versions") or []
        return project

    def public(self) -> dict[str, Any]:
        """What the UI needs: component payloads + progress, without internals."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "request": self.request,
            "components": {
                name: {"done": comp.done, "seconds": comp.seconds, "data": comp.data}
                for name, comp in self.components.items()
            },
            "progress": self.progress(),
            "events": self.events[-120:],
        }

    def progress(self) -> list[dict[str, Any]]:
        """Six user-facing stages, derived from real component state.

        Status is never simulated: a stage is ``done`` only when its components
        carry data, ``active`` only while the orchestrator is inside it.
        """
        has_upload = bool(self.request.get("upload_path"))
        mapping = {
            "understand": ["intent", "media"] if has_upload else ["intent"],
            "concept": ["concept", "brief", "visual_plan"],
            "assets": ["prompts", "assets"],
            "produce": ["script", "storyboard", "edit", "render"],
            "check": ["review", "final_review"],
            "publish": ["seo"],
        }
        out = []
        for key, label in USER_STAGES:
            names = mapping[key]
            done = [n for n in names if self.has(n)]
            if self.has("intent") is False and key == "understand":
                state = "pending"
            elif len(done) == len(names):
                state = "done"
            elif self.stage == key and self.status == "running":
                state = "active"
            elif done:
                state = "partial" if len(done) < len(names) else "done"
            else:
                state = "pending"
            out.append(
                {
                    "key": key,
                    "label": label,
                    "status": state,
                    "components": names,
                    "completed": len(done),
                    "total": len(names),
                }
            )
        return out


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_cache: dict[str, Project] = {}


class ProjectStore:
    """Filesystem-backed project memory (one directory per project)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else PROJECTS_DIR

    def dir_for(self, project_id: str) -> Path:
        return self.root / project_id

    def context_path(self, project_id: str) -> Path:
        return self.dir_for(project_id) / "brain" / "context.json"

    def create(self, request: dict[str, Any], title: str = "") -> Project:
        project_id = f"{slug(request.get('text') or title or 'campaign')}-{uuid.uuid4().hex[:6]}"
        project = Project(
            id=project_id,
            title=title or self._title_from(request),
            request=request,
        )
        self.save(project)
        return project

    @staticmethod
    def _title_from(request: dict[str, Any]) -> str:
        text = (request.get("text") or "").strip()
        if text:
            return text[:70]
        if request.get("upload_path"):
            return "Uploaded image campaign"
        return "Untitled campaign"

    def save(self, project: Project) -> Path:
        with _lock:
            path = self.context_path(project.id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(project.to_dict(), indent=1), encoding="utf-8")
            tmp.replace(path)
            _cache[project.id] = project
            return path

    def get(self, project_id: str) -> Optional[Project]:
        with _lock:
            if project_id in _cache:
                return _cache[project_id]
            path = self.context_path(project_id)
            if not path.exists():
                return None
            try:
                project = Project.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                return None
            _cache[project_id] = project
            return project

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.root.is_dir():
            return out
        for entry in sorted(self.root.iterdir(), reverse=True):
            path = self.context_path(entry.name)
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            project = Project.from_dict(raw)
            render = project.get("render") or {}
            out.append(
                {
                    "id": project.id,
                    "title": project.title,
                    "status": project.status,
                    "stage": project.stage,
                    "updated_at": project.updated_at,
                    "created_at": project.created_at,
                    "niche": (project.get("intent") or {}).get("niche"),
                    "concept": (project.get("concept") or {}).get("selected", {}).get("name"),
                    "poster": render.get("poster_url"),
                    "video": (render.get("video_url")),
                    "progress": project.progress(),
                }
            )
        return out

    def delete(self, project_id: str) -> bool:
        with _lock:
            _cache.pop(project_id, None)
        path = self.context_path(project_id)
        if path.exists():
            path.unlink()
            return True
        return False


STORE = ProjectStore()
