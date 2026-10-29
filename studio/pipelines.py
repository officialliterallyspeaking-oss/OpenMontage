"""Studio generation pipelines — thin orchestration over the repository's tools.

Three flows, all of which end up as files in a real OpenMontage project
workspace:

``run_image_job``
    prompt -> ``image_selector`` -> PNG. When no image provider is configured
    and the caller allows it, a clearly-labelled placeholder poster is drawn
    from the prompt instead.

``run_video_from_text``
    prompt -> image(s) -> FFmpeg camera motion -> MP4. This is the same
    still-to-motion path the repo's post pipeline uses, so it works without
    Node/Remotion. When a video model *is* configured the caller can ask for
    ``engine="video_model"`` instead, which goes through ``video_selector``.

``run_video_from_image``
    uploaded still -> FFmpeg camera motion -> MP4, or image-to-video through
    ``video_selector`` when configured.

Every run: writes ``project.json`` via ``lib.checkpoint.init_project``, emits
``lib.events`` tool events (so the Backlot board lights up), and records
provider provenance on the produced assets.
"""

from __future__ import annotations

import shutil
import threading
import traceback
from pathlib import Path
from typing import Any, Optional

from studio import jobs as store
from studio.jobs import Job
from studio.motion import (
    ASPECTS,
    demo_poster,
    poster_frame,
    probe,
    render_motion_video,
    image_size,
)
from studio.repo_bridge import PROJECTS_DIR, registry

# Two renders at once keeps the UI responsive without thrashing CPU.
_slots = threading.BoundedSemaphore(2)


# ---------------------------------------------------------------------------
# workspace helpers
# ---------------------------------------------------------------------------

def _init_workspace(job: Job) -> Path:
    """Create the canonical OpenMontage project layout + marker file."""
    from lib.checkpoint import init_project

    project_dir = Path(job.project_dir)
    init_project(
        job.project_id,
        title=job.prompt[:90] or "Studio job",
        pipeline_type="studio",
        style_playbook=job.style or "clean-professional",
    )
    (project_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    return project_dir


def _emit(project_dir: Path, event: dict[str, Any]) -> None:
    try:
        from lib.events import emit_event

        emit_event(project_dir, event)
    except Exception:
        pass


def _write_request_artifact(job: Job, project_dir: Path) -> None:
    import json

    payload = {
        "version": "1.0",
        "job_id": job.id,
        "kind": job.kind,
        "prompt": job.prompt,
        "engine": job.engine,
        "style": job.style,
        "aspect": job.aspect,
        "duration_seconds": job.duration_seconds,
        "motion": job.motion,
        "provider_requested": job.provider,
        "provider_used": job.provider_announcement,
        "created_at": job.created_at,
        "interface": "openmontage-studio",
    }
    path = project_dir / "artifacts" / "studio_request.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _dimensions(aspect: str) -> tuple[int, int]:
    return ASPECTS.get(aspect, ASPECTS["16:9"])


# ---------------------------------------------------------------------------
# image step
# ---------------------------------------------------------------------------

def _image_tool_inputs(job: Job, output_path: Path, index: int) -> dict[str, Any]:
    width, height = _dimensions(job.aspect)
    inputs: dict[str, Any] = {
        "prompt": job.prompt,
        "output_path": str(output_path),
        "aspect_ratio": job.aspect,
        "width": width,
        "height": height,
    }
    if job.provider and job.provider != "auto":
        inputs["preferred_provider"] = job.provider
    if index:
        inputs["seed"] = 101 + index * 7
    return inputs


def _generate_image(job: Job, output_path: Path, index: int, project_dir: Path) -> dict[str, Any]:
    """Generate one image. Returns provenance metadata."""
    reg = registry()
    tool = reg.get("image_selector")
    if tool is None:
        raise RuntimeError("image_selector is missing from the tool registry")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _emit(project_dir, {"tool": "image_selector", "event": "start", "output_path": str(output_path)})

    result = tool.execute(_image_tool_inputs(job, output_path, index))

    _emit(
        project_dir,
        {
            "tool": "image_selector",
            "event": "finish",
            "output_path": str(output_path),
            "success": bool(result.success),
            "cost_usd": float(result.cost_usd or 0.0),
        },
    )

    if result.success:
        data = result.data or {}
        produced = Path(data.get("output_path") or data.get("output") or output_path)
        if not produced.exists() and data.get("image_paths"):
            produced = Path(data["image_paths"][0])
        if not produced.exists():
            raise RuntimeError(
                "Provider reported success but produced no file. "
                f"Returned: {sorted(data)[:8]}"
            )
        if produced != output_path:
            shutil.copy2(produced, output_path)
        job.cost_usd += float(result.cost_usd or 0.0)
        job.provider_announcement.update(
            selected=data.get("selected_provider") or job.provider_announcement.get("selected"),
            selected_tool=data.get("selected_tool"),
            status="generated",
        )
        return {
            "provenance": "model",
            "tool": data.get("selected_tool") or "image_selector",
            "provider": data.get("selected_provider") or "unknown",
            "model": data.get("model") or data.get("model_name"),
            "selection_reason": data.get("selection_reason"),
        }

    raise RuntimeError(result.error or "image generation failed")


def _placeholder_image(job: Job, output_path: Path, index: int) -> dict[str, Any]:
    width, height = _dimensions(job.aspect)
    demo_poster(
        job.prompt,
        output_path,
        width=width,
        height=height,
        style=job.style,
        variant=index,
    )
    return {
        "provenance": "placeholder",
        "tool": "studio.motion.demo_poster",
        "provider": "local",
        "model": "deterministic-playbook-poster",
    }


# ---------------------------------------------------------------------------
# video step
# ---------------------------------------------------------------------------

def _video_from_stills(
    job: Job,
    stills: list[Path],
    project_dir: Path,
    out_path: Path,
) -> dict[str, Any]:
    _emit(project_dir, {"tool": "ffmpeg_motion", "event": "start", "output_path": str(out_path)})
    job.step("motion", "running", f"{len(stills)} still(s) → {job.aspect} @ {job.motion}")
    job.note(
        f"Rendering motion with ffmpeg (preset={job.motion}, {job.duration_seconds}s, "
        f"aspect={job.aspect})"
    )
    rendered = render_motion_video(
        stills,
        out_path,
        preset=job.motion,
        aspect=job.aspect,
        total_seconds=job.duration_seconds,
        workdir=project_dir / "renders" / ".motion_tmp" / job.id,
    )
    _emit(
        project_dir,
        {
            "tool": "ffmpeg_motion",
            "event": "finish",
            "output_path": str(out_path),
            "success": True,
            "cost_usd": 0.0,
        },
    )
    return rendered


def _video_from_model(
    job: Job,
    prompt: str,
    project_dir: Path,
    out_path: Path,
    reference_image: Optional[Path],
) -> dict[str, Any]:
    """Text- or image-to-video through the repo's video_selector."""
    reg = registry()
    tool = reg.get("video_selector")
    if tool is None:
        raise RuntimeError("video_selector is missing from the tool registry")

    inputs: dict[str, Any] = {
        "prompt": prompt,
        "output_path": str(out_path),
        "aspect_ratio": job.aspect,
        "duration": int(max(2, round(job.duration_seconds))),
        "operation": "image_to_video" if reference_image else "text_to_video",
    }
    if reference_image:
        inputs["reference_image_path"] = str(reference_image)
    if job.provider and job.provider != "auto":
        inputs["preferred_provider"] = job.provider

    _emit(project_dir, {"tool": "video_selector", "event": "start", "output_path": str(out_path)})
    job.note(
        "Calling video_selector "
        f"({'image_to_video' if reference_image else 'text_to_video'}, "
        f"provider={job.provider or 'auto'})"
    )
    result = tool.execute(inputs)
    _emit(
        project_dir,
        {
            "tool": "video_selector",
            "event": "finish",
            "output_path": str(out_path),
            "success": bool(result.success),
            "cost_usd": float(result.cost_usd or 0.0),
        },
    )
    if not result.success:
        raise RuntimeError(result.error or "video generation failed")

    data = result.data or {}
    produced = Path(data.get("output_path") or data.get("output") or out_path)
    if not produced.exists() and data.get("video_paths"):
        produced = Path(data["video_paths"][0])
    if not produced.exists():
        raise RuntimeError("Video provider returned success but no file on disk")
    if produced != out_path:
        shutil.copy2(produced, out_path)

    job.cost_usd += float(result.cost_usd or 0.0)
    job.provider_announcement.update(
        selected=data.get("selected_provider") or job.provider_announcement.get("selected"),
        selected_tool=data.get("selected_tool"),
        status="generated",
    )
    info = probe(out_path)
    return {
        "output": str(out_path),
        "duration_seconds": info.get("duration_seconds", job.duration_seconds),
        "width": info.get("width"),
        "height": info.get("height"),
        "preset": "provider",
        "provenance": "model",
        "tool": data.get("selected_tool") or "video_selector",
        "provider": data.get("selected_provider") or "unknown",
        "model": data.get("model"),
    }


def _finalize_video(job: Job, project_dir: Path, rendered: dict[str, Any]) -> None:
    video_path = Path(rendered["output"])
    info = probe(video_path)
    still_path = video_path.with_suffix(".jpg")
    poster_frame(video_path, still_path, at=max(0.4, min(1.6, job.duration_seconds / 3)))
    job.video = {
        "path": str(video_path),
        "url": _url(video_path),
        "poster_url": _url(still_path) if still_path.exists() else None,
        "duration_seconds": info.get("duration_seconds", rendered.get("duration_seconds")),
        "width": info.get("width", rendered.get("width")),
        "height": info.get("height", rendered.get("height")),
        "bytes": video_path.stat().st_size,
        "preset": rendered.get("preset"),
        "provenance": rendered.get("provenance", "local"),
        "tool": rendered.get("tool", "ffmpeg_motion"),
        "provider": rendered.get("provider", "local"),
        "model": rendered.get("model"),
    }
    job.step("motion", "done", Path(job.video["url"]).name)
    job.note(
        f"Wrote {job.video['width']}x{job.video['height']} · "
        f"{job.video['duration_seconds']}s · {job.video['bytes'] // 1024} KB"
    )


_PLATFORM_BY_ASPECT = {
    "16:9": "youtube",
    "4:3": "youtube",
    "9:16": "tiktok",
    "1:1": "instagram",
    "4:5": "instagram",
}

_TONE_BY_STYLE = {
    "clean-professional": "educational",
    "premium-minimalist": "corporate",
    "flat-motion-graphics": "playful",
    "minimalist-diagram": "educational",
    "anime-ghibli": "cinematic",
}


def _brief(job: Job) -> dict[str, Any]:
    """The schema-valid `brief` artifact for a single-request Studio run.

    The prompt is kept verbatim: a Studio user must be able to trace what they
    typed to what was generated.
    """
    prompt = job.prompt or "Untitled"
    key_points = [
        chunk.strip()
        for chunk in prompt.replace(";", ",").split(",")
        if chunk.strip()
    ][:6] or [prompt]

    brief = {
        "version": "1.0",
        "title": prompt[:80],
        "hook": prompt.split(".")[0][:160] or prompt[:160],
        "key_points": key_points,
        "tone": _TONE_BY_STYLE.get(job.style, "cinematic"),
        "style": job.style or "clean-professional",
        "target_platform": _PLATFORM_BY_ASPECT.get(job.aspect, "generic"),
        "target_duration_seconds": (
            0 if job.kind == "image" else float(job.duration_seconds)
        ),
        "metadata": {
            "interface": "openmontage-studio",
            "job_id": job.id,
            "request_kind": job.kind,
            "aspect": job.aspect,
            "prompt_verbatim": prompt,
        },
    }
    import json

    path = Path(job.project_dir) / "artifacts" / "brief.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    return brief


def record_brief(job: Job) -> None:
    """Stage `idea` completed — the request, distilled into a canonical brief."""
    _write_checkpoint(job, "idea", "completed", {"brief": _brief(job)})


def _write_checkpoint(
    job: Job,
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    *,
    cost_usd: float = 0.0,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Persist a real OpenMontage checkpoint for this Studio run."""
    try:
        from lib.checkpoint import write_checkpoint

        write_checkpoint(
            PROJECTS_DIR,
            job.project_id,
            stage,
            status,
            artifacts,
            pipeline_type="studio",
            style_playbook=job.style or "clean-professional",
            cost_snapshot={
                "total_spent_usd": round(job.cost_usd + cost_usd, 4),
                "total_reserved_usd": 0.0,
                "budget_remaining_usd": 0.0,
            },
            metadata={"interface": "openmontage-studio", "job_id": job.id, **(metadata or {})},
        )
    except Exception as exc:  # never let bookkeeping break a render
        job.note(f"checkpoint {stage} skipped: {str(exc)[:160]}")


def _asset_manifest(job: Job) -> dict[str, Any]:
    assets = []
    for asset in job.assets:
        assets.append(
            {
                "id": asset["id"],
                "type": "image",
                "path": asset["path"],
                "source_tool": asset.get("tool") or "image_selector",
                "scene_id": asset.get("scene_id") or "sc1",
                "prompt": job.prompt,
                "model": asset.get("model") or "",
                "provider": asset.get("provider") or "",
                "cost_usd": 0.0,
                "format": Path(asset["path"]).suffix.lstrip(".") or "png",
                "resolution": f"{asset.get('width') or 0}x{asset.get('height') or 0}",
            }
        )
    manifest = {
        "version": "1.0",
        "assets": assets,
        "total_cost_usd": round(job.cost_usd, 4),
        "metadata": {
            "interface": "openmontage-studio",
            "request": job.kind,
            "aspect": job.aspect,
            "provenance": sorted({a.get("provenance", "unknown") for a in job.assets}),
        },
    }
    import json

    path = Path(job.project_dir) / "artifacts" / "asset_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _render_report(job: Job) -> dict[str, Any]:
    video = job.video or {}
    report = {
        "version": "1.0",
        "outputs": [
            {
                "path": video.get("path", ""),
                "format": "mp4",
                "codec": "libx264",
                "resolution": f"{video.get('width') or 0}x{video.get('height') or 0}",
                "fps": 30,
                "duration_seconds": video.get("duration_seconds") or 0,
                "file_size_bytes": video.get("bytes") or 0,
                "platform_target": job.aspect,
            }
        ],
        "render_time_seconds": 0,
        # Enum in schemas/artifacts/render_report.schema.json: a single-shot
        # camera move reads as a cinematic beat; a model clip as animation-first.
        "render_grammar": (
            "cinematic-trailer" if video.get("tool") == "ffmpeg_motion" else "animation-first"
        ),
        "warnings": (
            ["Source frames are labelled placeholder art (no image provider configured)."]
            if job.placeholder
            else []
        ),
        "verification_notes": [
            f"camera move: {job.motion}",
            f"engine: {'video model' if job.engine == 'video_model' else 'local ffmpeg'}",
            f"stills: {len(job.assets)}",
        ],
        "metadata": {
            "interface": "openmontage-studio",
            "job_id": job.id,
            "provider": video.get("provider"),
        },
    }
    import json

    path = Path(job.project_dir) / "artifacts" / "render_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def record_assets(job: Job) -> None:
    """Stage `assets` completed — canonical asset_manifest on the board."""
    if not job.assets:
        return
    _write_checkpoint(
        job,
        "assets",
        "completed",
        {"asset_manifest": _asset_manifest(job)},
        metadata={"asset_count": len(job.assets)},
    )


def record_render(job: Job) -> None:
    """Stage `compose` completed — canonical render_report on the board."""
    if not job.video:
        return
    _write_checkpoint(
        job,
        "compose",
        "completed",
        {"render_report": _render_report(job)},
        metadata={
            "asset_count": len(job.assets),
            "render_tool": job.video.get("tool"),
        },
    )


def _url(path: Path) -> str:
    """Map an on-disk project path to the Studio media route."""
    try:
        rel = Path(path).resolve().relative_to(PROJECTS_DIR.resolve())
    except Exception:
        return ""
    return f"/media/projects/{rel.as_posix()}"


def _record_asset(job: Job, path: Path, meta: dict[str, Any], index: int) -> None:
    width = height = None
    try:
        width, height = image_size(path)
    except Exception:
        pass
    job.assets.append(
        {
            "id": f"{job.id}-img-{index}",
            "path": str(path),
            "url": _url(path),
            "filename": path.name,
            "width": width,
            "height": height,
            "bytes": path.stat().st_size if path.exists() else 0,
            "provenance": meta.get("provenance", "unknown"),
            "tool": meta.get("tool"),
            "provider": meta.get("provider"),
            "model": meta.get("model"),
            "scene_id": f"sc{index + 1}",
        }
    )


# ---------------------------------------------------------------------------
# job runners
# ---------------------------------------------------------------------------

def _guarded(job: Job, body) -> None:
    with _slots:
        job.status = "running"
        job.touch()
        store.save()
        try:
            body()
            job.status = "done"
            job.step("done", "done", "complete")
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:1200]
            job.step("failed", "failed", str(exc)[:300])
            job.note(f"FAILED: {exc}")
            if job.steps:
                for step in job.steps:
                    if step.status in ("running", "pending"):
                        step.status = "failed"
        finally:
            job.touch()
            store.save()
            _write_request_artifact(job, Path(job.project_dir))


def _base_steps(job: Job, names: list[str]) -> None:
    for name in names:
        job.step(name, "pending")


def _announce(job: Job, capability: str) -> None:
    """Record which provider path will be used, per the repo's decision contract."""
    from studio.repo_bridge import catalog, provider_choices

    choices = provider_choices(capability)
    available = [c["provider"] for c in choices]
    requested = job.provider if job.provider and job.provider != "auto" else None

    if requested and requested not in available:
        job.provider_announcement = {
            "capability": capability,
            "requested": requested,
            "status": "unavailable",
            "available": available,
            "reason": f"{requested} is not configured (missing credentials or runtime).",
        }
        job.note(f"{requested} is unavailable — falling back.")
    elif available:
        chosen = requested or available[0]
        job.provider_announcement = {
            "capability": capability,
            "requested": job.provider,
            "status": "selected",
            "selected": chosen,
            "available": available,
        }
        job.note(f"Provider for {capability}: {chosen} (available: {', '.join(available)})")
    else:
        menu = catalog()["capabilities"].get(capability, {})
        job.provider_announcement = {
            "capability": capability,
            "requested": job.provider,
            "status": "none_configured",
            "available": [],
            "configured": f"{menu.get('configured', 0)}/{menu.get('total', 0)}",
        }
        job.note(f"No {capability} provider configured ({menu.get('configured', 0)}/{menu.get('total', 0)}).")


def run_image_job(job: Job) -> None:
    def body() -> None:
        project_dir = _init_workspace(job)
        _write_request_artifact(job, project_dir)
        record_brief(job)
        _base_steps(job, ["provider", "generate", "done"])

        _announce(job, "image_generation")
        job.step("provider", "done", job.provider_announcement.get("status", ""))

        images_dir = project_dir / "assets" / "images"
        job.step("generate", "running")
        made_any = False
        for index in range(max(1, job.count)):
            out = images_dir / f"studio_{index + 1:02d}.png"
            meta: Optional[dict[str, Any]] = None
            try:
                meta = _generate_image(job, out, index, project_dir)
                job.note(
                    f"Image {index + 1}: {meta['provider']} "
                    f"({meta.get('model') or meta['tool']})"
                )
            except Exception as exc:
                job.note(f"Image {index + 1}: no model output ({str(exc)[:160]})")
                if job.allow_placeholder:
                    meta = _placeholder_image(job, out, index)
                    job.placeholder = True
                    job.note("Using labelled placeholder art for this frame.")
                else:
                    raise
            if meta and out.exists():
                _record_asset(job, out, meta, index)
                made_any = True

        if not made_any:
            raise RuntimeError(
                "No image could be produced. Configure an image provider under Keys, "
                "or enable placeholder art."
            )
        job.step("generate", "done", f"{len(job.assets)} image(s)")
        record_assets(job)

    _guarded(job, body)


def run_video_from_text(job: Job) -> None:
    def body() -> None:
        project_dir = _init_workspace(job)
        _write_request_artifact(job, project_dir)
        record_brief(job)
        _base_steps(job, ["provider", "stills", "motion", "done"])

        images_dir = project_dir / "assets" / "images"
        video_dir = project_dir / "assets" / "video"
        video_dir.mkdir(parents=True, exist_ok=True)
        out_video = project_dir / "renders" / "final.mp4"
        stills: list[Path] = []

        if job.engine == "video_model":
            _announce(job, "video_generation")
            job.step("provider", "done", job.provider_announcement.get("status", ""))
            job.step("stills", "skipped", "text-to-video")
            job.step("motion", "running", "video model")
            try:
                rendered = _video_from_model(job, job.prompt, project_dir, out_video, None)
                _finalize_video(job, project_dir, rendered)
                return
            except Exception as exc:
                job.note(f"Video model unavailable ({str(exc)[:160]}). Falling back to stills + motion.")
                job.step("motion", "pending")
                job.engine = "motion"
        else:
            job.step("provider", "done", "local ffmpeg motion")
            job.step("motion", "pending")

        # --- stills ---------------------------------------------------------
        job.step("stills", "running")
        _announce(job, "image_generation")
        for index in range(max(1, job.count)):
            out = images_dir / f"studio_{index + 1:02d}.png"
            meta: Optional[dict[str, Any]] = None
            try:
                meta = _generate_image(job, out, index, project_dir)
                job.note(f"Still {index + 1}: {meta['provider']} ({meta.get('model') or meta['tool']})")
            except Exception as exc:
                job.note(f"Still {index + 1}: no model output ({str(exc)[:140]})")
                if not job.allow_placeholder:
                    raise
                meta = _placeholder_image(job, out, index)
                job.placeholder = True
                job.note("Using labelled placeholder art for this frame.")
            if meta and out.exists():
                _record_asset(job, out, meta, index)
                stills.append(out)
        if not stills:
            raise RuntimeError("No stills were produced for the video.")
        job.step("stills", "done", f"{len(stills)} still(s)")
        record_assets(job)

        # --- motion ---------------------------------------------------------
        rendered = _video_from_stills(job, stills, project_dir, out_video)
        _finalize_video(job, project_dir, rendered)
        record_render(job)

    _guarded(job, body)


def run_video_from_image(job: Job, upload_path: Path) -> None:
    def body() -> None:
        project_dir = _init_workspace(job)
        _write_request_artifact(job, project_dir)
        record_brief(job)
        _base_steps(job, ["provider", "ingest", "motion", "done"])

        images_dir = project_dir / "assets" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        out_video = project_dir / "renders" / "final.mp4"

        job.step("ingest", "running")
        suffix = upload_path.suffix.lower() or ".png"
        source_copy = images_dir / f"source{suffix}"
        shutil.copy2(upload_path, source_copy)
        width, height = image_size(source_copy)
        job.note(f"Uploaded source image {width}x{height} ({source_copy.name})")
        meta = {
            "provenance": "upload",
            "tool": "upload",
            "provider": "user",
            "model": None,
        }
        _record_asset(job, source_copy, meta, 0)
        job.step("ingest", "done", f"{width}x{height}")

        if job.engine == "video_model":
            _announce(job, "video_generation")
            job.step("provider", "done", job.provider_announcement.get("status", ""))
            job.step("motion", "running", "image-to-video model")
            try:
                rendered = _video_from_model(
                    job,
                    job.prompt or "cinematic camera move, natural motion",
                    project_dir,
                    out_video,
                    source_copy,
                )
                _finalize_video(job, project_dir, rendered)
                return
            except Exception as exc:
                job.note(
                    f"Image-to-video model unavailable ({str(exc)[:160]}). "
                    "Falling back to local camera motion."
                )
                job.step("motion", "pending")
        else:
            job.step("provider", "done", "local ffmpeg motion")

        rendered = _video_from_stills(job, [source_copy], project_dir, out_video)
        rendered["provenance"] = "local"
        _finalize_video(job, project_dir, rendered)
        record_assets(job)
        record_render(job)

    _guarded(job, body)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def start(kind: str, prompt: str, *, upload_path: Optional[Path] = None, **kwargs: Any) -> Job:
    job = store.create(kind, prompt, **kwargs)
    job.note(f"Job {job.id} created ({kind})")
    store.save()

    if kind == "image":
        target = run_image_job
        args: tuple = (job,)
    elif kind == "video_from_text":
        target = run_video_from_text
        args = (job,)
    elif kind == "video_from_image":
        if upload_path is None:
            raise ValueError("video_from_image requires an uploaded image")
        target = run_video_from_image
        args = (job, upload_path)
    else:
        raise ValueError(f"unknown job kind: {kind}")

    def runner() -> None:
        try:
            target(*args)
        except Exception:  # pragma: no cover - _guarded already catches
            job.status = "failed"
            job.error = traceback.format_exc()[-1200:]
            store.save()

    threading.Thread(target=runner, name=f"studio-{job.id}", daemon=True).start()
    return job
