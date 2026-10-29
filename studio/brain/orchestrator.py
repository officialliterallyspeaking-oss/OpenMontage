"""The conductor — sequences the four systems over one shared project.

The systems never call each other directly and never hand over files by hand;
they read and write components on the same `Project`. This module decides *what
to (re)compute* and in what order, which is what makes the studio feel like one
intelligence rather than four tools:

* **First run** — every component, in dependency order.
* **Refinement** — only the components whose inputs actually changed, plus
  everything downstream of them. Changing one scene's description re-renders
  that scene and re-cuts the video; it does not re-decide the concept and it
  does not rewrite the script.
* **Failure** — completed work is preserved. A failure marks the project failed
  with the step that broke and what was kept, and a retry resumes from there.

Progress is reported with the components that actually completed, so the UI can
say "Creating your visual assets" only while assets are genuinely being created.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from studio.brain import assembly, creative, director, growth, producer
from studio.brain import knowledge as kb
from studio.brain.projects import COMPONENTS, REPO_ROOT, STORE, Project, ProjectStore

ProgressFn = Optional[Callable[[str, str, float, dict[str, Any] | None], None]]

STAGE_OF = {
    "intent": "understand",
    "media": "understand",
    "concept": "concept",
    "brief": "concept",
    "hooks": "concept",
    "beats": "concept",
    "visual_plan": "concept",
    "prompts": "assets",
    "assets": "assets",
    "script": "produce",
    "storyboard": "produce",
    "scene_assets": "produce",
    "edit": "produce",
    "cues": "produce",
    "render": "produce",
    "review": "check",
    "final_review": "check",
    "seo": "publish",
}

ORDER = ["intent", "media", "concept", "brief", "hooks", "beats", "visual_plan", "prompts",
         "assets", "script", "storyboard", "scene_assets", "edit", "cues", "render", "review",
         "final_review", "seo"]


class Orchestrator:
    def __init__(self, store: ProjectStore | None = None) -> None:
        self.store = store or STORE

    # ------------------------------------------------------------------
    # planning
    # ------------------------------------------------------------------
    def needed(self, project: Project) -> list[str]:
        """Which components are missing or stale, in dependency order."""
        if not project.has("intent"):
            # the deliverable is decided by the request, so read it first
            return [c for c in (["intent", "media"] if project.request.get("upload_path") else ["intent"])
                    if not project.components[c].done]

        deliverable = (project.get("intent") or {}).get("deliverable", "video")
        required = {
            # a still deliverable stops at the artwork: no timeline, no render,
            # and therefore no video QA report claiming one
            "image": ["intent", "media", "concept", "brief", "hooks", "beats", "visual_plan",
                      "prompts", "assets", "seo"],
            "video": ORDER,
            "campaign": ORDER,
        }.get(deliverable, ORDER)
        if not project.request.get("upload_path"):
            required = [name for name in required if name != "media"]

        stale = []
        for name in required:
            comp = project.components[name]
            if not comp.done:
                stale.append(name)
                continue
            # a component whose dependency changed is stale even if it has data
            for dep in comp.deps:
                dep_comp = project.components[dep]
                if dep_comp.done and dep_comp.updated_at > comp.updated_at:
                    stale.append(name)
                    break
        return [name for name in required if name in set(stale)]

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def run(
        self,
        project: Project,
        *,
        progress: ProgressFn = None,
        only: Optional[list[str]] = None,
        provider: Optional[str] = None,
    ) -> Project:
        """Execute every stale component. Never discards completed work."""
        project.status = "running"
        project.error = None
        project_dir = self.store.dir_for(project.id)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "artifacts").mkdir(exist_ok=True)

        requested = set(only) if only is not None else None
        started = time.time()
        reused: list[str] = []
        executed: list[str] = []
        guard = 0

        try:
            # A fixpoint loop: the plan is recomputed after every step, so the
            # deliverable (decided by the intent step) can narrow what follows.
            while True:
                guard += 1
                if guard > len(COMPONENTS) + 2:
                    raise RuntimeError("orchestrator could not converge on a plan")
                pending = self.needed(project)
                if requested is not None:
                    pending = [name for name in pending if name in requested]
                pending = [name for name in ORDER if name in set(pending)]
                if not pending:
                    break
                name = pending[0]
                stage = STAGE_OF[name]
                project.stage = stage
                if progress:
                    progress(stage, _label(name), min(0.95, len(executed) / max(1, len(executed) + len(pending))),
                             {"component": name})
                t0 = time.time()
                self._step(project, name, project_dir, provider=provider)
                elapsed = time.time() - t0
                project.mark(name, elapsed)
                executed.append(name)
                if requested is not None:
                    requested.discard(name)
                project.event("studio", f"{name} complete", seconds=round(elapsed, 2))
                self.store.save(project)
            project.status = "complete"
            project.stage = "publish"
            project.event("studio", "all systems complete", seconds=round(time.time() - started, 1))
        except Exception as exc:  # preserve everything already built
            project.status = "failed"
            project.error = f"{type(exc).__name__}: {exc}"
            project.event("studio", f"stopped at {project.stage}: {exc}",
                          trace=traceback.format_exc()[-1200:])
        finally:
            self._persist_artifacts(project, project_dir)
            self.store.save(project)
            if progress:
                progress("done" if project.status == "complete" else "error",
                         "Ready to review" if project.status == "complete" else "Stopped — your work is safe",
                         1.0, {"status": project.status})
        return project

    def _step(self, project: Project, name: str, project_dir: Path, *, provider: Optional[str] = None) -> None:
        if name == "intent":
            media = project.get("media") if project.request.get("upload_path") else None
            if project.request.get("platform"):
                project.request.setdefault("explicit_platform", True)
            intent = director.interpret(project.request, media)
            project.put("intent", intent)
            project.event("director", f"Read the request as {intent['niche_label']} · "
                                      f"{intent['deliverable']} · {intent['duration_seconds']:.0f}s")
            return

        if name == "media":
            upload = project.request.get("upload_path")
            if not upload:
                return
            facts = creative.analyse_image(upload)
            project.put("media", facts)
            project.event("creative", f"Measured the source image — {facts['orientation']}, "
                                      f"brightness {facts['brightness']}, "
                                      f"{len(facts['palette'])} palette colours")
            return

        intent = project.get("intent") or {}
        niche = kb.NICHES.get(intent.get("niche", "generic"), kb.GENERIC)

        if name == "concept":
            decision = director.direct(project, intent)
            project.put("concept", decision["concept"])
            project.put("brief", decision["brief"])
            project.put("hooks", decision["hooks"])
            project.put("beats", decision["beats"])
            project.event(
                "director",
                f"Chose '{decision['concept']['selected']['name']}' "
                f"({decision['concept']['selected']['score']}/100) over "
                f"{len(decision['concept']['options']) - 1} other angles",
            )
            return

        concept = project.get("concept") or {}
        selected = concept.get("selected") or {}
        options = concept.get("options") or []

        if name == "brief":
            project.put("brief", director.build_brief(intent, selected, niche, options))
            return
        if name == "hooks":
            project.put("hooks", director.hook_set(intent, selected, niche, options))
            return
        if name == "beats":
            project.put("beats", director.beat_sheet(intent, selected))
            return

        beats = project.get("beats") or []
        if name == "visual_plan":
            plan = creative.plan_visuals(intent, selected, beats, project.get("media"))
            project.put("visual_plan", plan)
            project.event("creative", f"Planned {len(plan['shots'])} shots in "
                                      f"{' · '.join(plan['palette'][:3])}")
            return

        if name == "prompts":
            prompts = creative.build_prompts(intent, selected, project.get("visual_plan") or {})
            project.put("prompts", prompts)
            project.event("creative", f"Wrote {len(prompts['shots'])} model-ready prompts")
            return

        if name == "assets":
            result = creative.produce_assets(
                project_dir,
                intent,
                selected,
                project.get("visual_plan") or {},
                project.get("prompts") or {},
                upload_path=project.request.get("upload_path"),
                provider=provider or project.request.get("provider"),
                previous=(project.components["assets"].data if project.components["assets"].data else None),
                media=project.get("media"),
            )
            project.put("assets", result)
            project.event("creative", result["note"], used_model=result["used_model"])
            return

        if name == "script":
            script = producer.write_script(intent, selected, project.get("brief") or {}, beats)
            project.put("script", script)
            project.event("producer", f"Scripted {len(script['sections'])} sections "
                                      f"({'narrated' if (script.get('metadata') or {}).get('spoken') else 'text-on-screen'})")
            return

        if name == "storyboard":
            storyboard = producer.write_storyboard(
                intent, selected, project.get("script") or {}, project.get("visual_plan") or {}
            )
            project.put("storyboard", storyboard)
            # asset paths are runtime state, not part of the schema'd artifact
            by_shot = {a["shot_id"]: a for a in (project.get("assets") or {}).get("assets", [])}
            project.put("scene_assets", {
                shot_id: {"asset_path": asset["path"], "provenance": asset.get("provenance")}
                for shot_id, asset in by_shot.items()
            })
            project.event("producer", f"Storyboarded {len(storyboard['scenes'])} scenes with shot language")
            return

        storyboard = project.get("storyboard") or {}
        if name == "scene_assets":
            return  # written alongside the storyboard

        if name == "edit":
            edit = producer.write_edit_decisions(
                intent, selected, storyboard, project.get("visual_plan") or {},
                project.get("assets") or {}, project.get("cues") or [],
            )
            project.put("edit", edit)
            project.event("producer", f"Cut {len(edit['cuts'])} clips · runtime "
                                      f"{storyboard.get('total_duration_seconds', 0):.1f}s")
            return

        if name == "cues":
            cues = producer.build_cues(project.get("script") or {}, storyboard)
            project.put("cues", cues)
            project.event("producer", f"Timed {len(cues)} caption cues to the scenes")
            return

        if name == "render":
            video = self._render(project, project_dir, storyboard)
            project.put("render", video)
            project.event("producer", f"Rendered {video['width']}x{video['height']} · "
                                      f"{video['duration_seconds']}s · {video['bytes'] // 1024} KB")
            return

        if name == "review":
            review, final_review = producer.quality_check(
                Path((project.get("render") or {})["path"]),
                storyboard=storyboard,
                assets=project.get("assets") or {},
                cues=project.get("cues") or [],
                intent=intent,
                expected_seconds=float(intent.get("duration_seconds") or 0),
                promised_model=bool((project.get("assets") or {}).get("used_model")),
            )
            project.put("review", review)
            project.put("final_review", final_review)
            project.event("producer", f"QA {final_review['status']} · "
                                      f"{len(review['findings'])} finding(s)")
            return

        if name == "final_review":
            existing = project.get("final_review")
            review = project.get("review")
            if existing and review:
                return  # already produced alongside the review
            raise RuntimeError("final review requires the review step")

        if name == "seo":
            package = growth.build_package(
                intent=intent,
                concept=selected,
                brief=project.get("brief") or {},
                script=project.get("script") or {},
                storyboard=storyboard,
                cues=project.get("cues") or [],
                video=self._video_payload(project),
                assets=project.get("assets") or {},
                final_review=project.get("final_review"),
            )
            project.put("seo", package)
            project.event("growth", f"Publishing package ready — {package['hashtags']['count']} hashtags, "
                                    f"caption {package['caption']['characters']} chars")
            return

        raise RuntimeError(f"unknown component {name}")

    # ------------------------------------------------------------------
    # artifacts on disk
    # ------------------------------------------------------------------
    ARTIFACT_MAP = {
        "brief": "brief.json",
        "script": "script.json",
        "storyboard": "scene_plan.json",
        "edit": "edit_decisions.json",
        "review": "review.json",
        "final_review": "final_review.json",
    }

    def _persist_artifacts(self, project: Project, project_dir: Path) -> None:
        """Write schema-shaped artifacts, validated by the repository's own schemas.

        Using ``jsonschema`` against ``schemas/artifacts/*.json`` means the studio
        cannot drift from the artifacts the rest of OpenMontage consumes — if a
        field is renamed here, the pipeline reports it instead of shipping a file
        that silently fails someone else's contract test.
        """
        import json

        out = project_dir / "artifacts"
        schema_dir = REPO_ROOT / "schemas" / "artifacts"
        problems: list[str] = []
        try:
            out.mkdir(parents=True, exist_ok=True)
            for component, filename in self.ARTIFACT_MAP.items():
                data = project.get(component)
                if not data:
                    continue
                schema_path = schema_dir / f"{Path(filename).stem}.schema.json"
                if schema_path.is_file():
                    try:
                        import jsonschema

                        jsonschema.validate(
                            instance=data,
                            schema=json.loads(schema_path.read_text(encoding="utf-8")),
                        )
                    except ImportError:
                        pass
                    except Exception as exc:  # record, never crash the run
                        problems.append(f"{filename}: {str(exc).splitlines()[0][:180]}")
                (out / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")
            if problems:
                project.event("studio", "artifact schema warnings", problems=problems)
            extra = {
                "studio_concept.json": project.get("concept"),
                "studio_visual_plan.json": project.get("visual_plan"),
                "studio_assets.json": project.get("assets"),
                "studio_prompts.json": project.get("prompts"),
                "publish_log.json": ((project.get("seo") or {}).get("publish_log")),
                "studio_progress.json": {
                    "status": project.status,
                    "stage": project.stage,
                    "progress": project.progress(),
                    "components": {k: project.components[k].to_dict() for k in COMPONENTS},
                },
            }
            for filename, data in extra.items():
                if data:
                    (out / filename).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception as exc:  # artifact writing must never break a run
            project.event("studio", f"could not write artifacts: {exc}")

    # ------------------------------------------------------------------
    # rendering + fallbacks
    # ------------------------------------------------------------------
    def _render(self, project: Project, project_dir: Path, storyboard: dict[str, Any]) -> dict[str, Any]:
        intent = project.get("intent") or {}
        plan = project.get("visual_plan") or {}
        cues = project.get("cues") or []
        aspect = "9:16" if intent.get("platform") == "tiktok" else "16:9"
        renders = project_dir / "renders"
        renders.mkdir(parents=True, exist_ok=True)
        out = renders / "final.mp4"

        cache: dict[str, str] = {}
        linked = project.get("scene_assets") or {}
        shots = []
        for scene in storyboard["scenes"]:
            shots.append(
                {
                    "id": scene["id"],
                    "duration_seconds": scene["end_seconds"] - scene["start_seconds"],
                    "asset_path": (linked.get(scene["id"]) or {}).get("asset_path"),
                    "movement": scene.get("movement") or "ken_burns",
                    "transition_in": scene.get("transition_in", "cut"),
                }
            )

        media = project.get("media") or {}
        brightness = float(media.get("brightness") or 0.5)
        # bright source frames need help for caption contrast; the flat-design
        # frames are already dark, so this only kicks in when it is measured
        scrim = 0.0
        if cues:
            if media.get("brightness") is not None and brightness > 0.55:
                scrim = min(0.72, 0.34 + (brightness - 0.55) * 1.2)
            elif all(
                a.get("provenance") == "local"
                for a in (project.get("assets") or {}).get("assets", [])
            ):
                scrim = 0.0  # our own design frames are already dark
        try:
            result = assembly.render_timeline(
                shots, out, aspect=aspect, cues=cues, palette=plan.get("palette", []),
                kicker="", workdir=project_dir / "renders" / ".timeline", cache=cache,
                scrim_strength=scrim,
            )
        except Exception as first:
            # recovery path 1: drop captions rather than lose the whole render
            project.event("producer", f"Caption burn failed, retrying without captions: {first}")
            result = assembly.render_timeline(
                shots, out, aspect=aspect, cues=[], palette=plan.get("palette", []),
                workdir=project_dir / "renders" / ".timeline", cache=cache,
            )
            result["caption_fallback"] = str(first)[:300]

        width, height = result["width"], result["height"]
        return {
            "path": result["output"],
            "poster_path": result["poster"],
            "url": "final.mp4",
            "poster_url": "final.jpg",
            "duration_seconds": result["duration_seconds"],
            "width": width,
            "height": height,
            "bytes": result["bytes"],
            "aspect": aspect,
            "resolution": f"{width}x{height}",
            "scenes": result["scenes"],
            "caption_cues": result["caption_cues"],
            "has_captions": bool(cues) and "caption_fallback" not in result,
            "caption_fallback": result.get("caption_fallback"),
            "runtime": "ffmpeg",
            "provenance": self._video_provenance(project),
        }

    @staticmethod
    def _video_provenance(project: Project) -> str:
        provenance = [a.get("provenance") for a in (project.get("assets") or {}).get("assets", [])]
        if not provenance:
            return "unknown"
        if all(p == "model" for p in provenance):
            return "model"
        if all(p == "source" for p in provenance):
            return "source"
        if any(p == "model" for p in provenance):
            return "mixed"
        return "local_preview"

    def _video_payload(self, project: Project) -> dict[str, Any] | None:
        render = project.get("render")
        if not render:
            return None
        return {
            "path": render["path"],
            "url": render["url"],
            "duration_seconds": render["duration_seconds"],
            "aspect": render["aspect"],
            "resolution": render["resolution"],
            "bytes": render["bytes"],
            "provenance": render["provenance"],
        }

    # ------------------------------------------------------------------
    # refinement
    # ------------------------------------------------------------------
    REFINEMENTS = {
        "hook": {
            "label": "Rewrite the opening line",
            "invalidates": ["hooks", "brief", "script"],
            "why": "Copy changes downstream of the concept; the artwork does not.",
        },
        "scene": {
            "label": "Change one scene",
            "invalidates": ["prompts", "assets", "storyboard", "edit", "cues", "render",
                            "review", "final_review", "seo"],
            "why": "Only shots whose prompt changed are regenerated; the script and every "
                   "untouched scene are reused.",
        },
        "caption_text": {
            "label": "Edit a caption line",
            "invalidates": ["script", "storyboard", "edit", "cues", "render", "review",
                            "final_review", "seo"],
            "why": "Captions carry the words, so the burn is rebuilt; the visuals are untouched.",
        },
        "concept": {
            "label": "Choose a different angle",
            "invalidates": ["concept", "brief", "hooks", "beats", "visual_plan", "prompts",
                            "assets", "script", "storyboard", "edit", "cues", "render",
                            "review", "final_review", "seo"],
            "why": "A different concept changes the structure, so everything downstream follows.",
        },
        "palette": {
            "label": "Change the colour direction",
            "invalidates": ["visual_plan", "prompts", "assets", "render", "review",
                            "final_review", "seo"],
            "why": "Grade and artwork change; script, timing and storyboard structure do not.",
        },
        "duration": {
            "label": "Change the length",
            "invalidates": ["concept", "brief", "hooks", "beats", "visual_plan", "prompts",
                            "assets", "script", "storyboard", "edit", "cues", "render",
                            "review", "final_review", "seo"],
            "why": "Timing runs through every beat, so the structure is rebuilt to fit.",
        },
        "sound": {
            "label": "Change the sound direction",
            "invalidates": ["seo"],
            "why": "The export is silent by design; only the sound brief changes.",
        },
    }

    def preview(self, project: Project, operation: str) -> list[str]:
        """Which components *would* be recomputed — without touching the project.

        The UI shows this before you commit, so it has to be a pure read. An
        earlier version mutated the graph here and the real run then found
        nothing left to invalidate.
        """
        spec = self.REFINEMENTS.get(operation)
        if not spec:
            raise ValueError(f"unknown refinement '{operation}'")
        targets = set(spec["invalidates"])
        changed = True
        while changed:
            changed = False
            for name in COMPONENTS:
                if name in targets or not project.components[name].done:
                    continue
                if any(dep in targets for dep in project.components[name].deps):
                    targets.add(name)
                    changed = True
        return [name for name in ORDER if name in targets]

    def refine(self, project: Project, operation: str, payload: dict[str, Any], *, progress: ProgressFn = None) -> Project:
        spec = self.REFINEMENTS.get(operation)
        if not spec:
            raise ValueError(f"unknown refinement '{operation}'")
        intent = dict(project.get("intent") or {})
        concept = dict(project.get("concept") or {})
        selected = dict(concept.get("selected") or {})
        niche = kb.NICHES.get(intent.get("niche", "generic"), kb.GENERIC)
        keep: tuple[str, ...] = ()

        if operation == "hook":
            hook = (payload.get("hook") or "").strip()
            if not hook:
                raise ValueError("a new hook is required")
            selected["hooks"] = [hook] + [h for h in selected.get("hooks", []) if h != hook]
            selected["hook"] = hook
            concept["selected"] = selected
            project.put("concept", concept)
            brief = dict(project.get("brief") or {})
            brief["hook"] = hook
            project.put("brief", brief)
            project.put("hooks", director.hook_set(intent, selected, niche, concept.get("options")))

        elif operation == "scene":
            index = int(payload.get("scene_index", 0))
            description = (payload.get("description") or "").strip()
            plan = dict(project.get("visual_plan") or {})
            shots = [dict(s) for s in plan.get("shots", [])]
            if not 0 <= index < len(shots):
                raise ValueError("scene index out of range")
            if description:
                shots[index]["description"] = description
            if payload.get("movement"):
                shots[index]["movement"] = payload["movement"]
            plan["shots"] = shots
            project.put("visual_plan", plan)
            prompts = dict(project.get("prompts") or {})
            prompt_shots = [dict(p) for p in prompts.get("shots", [])]
            for entry in prompt_shots:
                if entry.get("shot_id") == shots[index]["id"]:
                    entry["prompt"] = (
                        f"{shots[index]['description']}. {shots[index]['framing']} framing, "
                        f"{shots[index]['lighting']}. {prompts.get('style_block', '')}"
                    )
            prompts["shots"] = prompt_shots
            project.put("prompts", prompts)
            keep = ("assets",)

        elif operation == "caption_text":
            section_id = payload.get("section_id")
            text = (payload.get("text") or "").strip()
            if not section_id or not text:
                raise ValueError("section_id and text are required")
            script = dict(project.get("script") or {})
            sections = [dict(s) for s in script.get("sections", [])]
            hit = False
            for section in sections:
                if section["id"] == section_id:
                    section["text"] = text
                    hit = True
            if not hit:
                raise ValueError("unknown script section")
            script["sections"] = sections
            project.put("script", script)

        elif operation == "concept":
            concept_id = payload.get("concept_id")
            options = concept.get("options", [])
            choice = next((o for o in options if o["id"] == concept_id), None)
            if not choice:
                raise ValueError("unknown concept")
            previous_name = selected.get("name")
            new_selected = {k: v for k, v in choice.items() if k != "score"}
            concept["selected"] = new_selected
            concept["changed_from"] = previous_name
            concept["why_not"] = f"Switched by you to '{choice['name']}'."
            project.put("concept", concept)
            project.put("brief", director.build_brief(intent, new_selected, niche, options))
            project.put("hooks", director.hook_set(intent, new_selected, niche, options))
            project.put("beats", director.beat_sheet(intent, new_selected))

        elif operation == "palette":
            palette = payload.get("palette")
            if not (isinstance(palette, list) and len(palette) >= 2):
                raise ValueError("palette needs at least two colours")
            plan = dict(project.get("visual_plan") or {})
            plan["palette"] = palette
            project.put("visual_plan", plan)
            prompts = dict(project.get("prompts") or {})
            prompts["style_block"] = creative._grade(intent, project.get("media"))
            project.put("prompts", prompts)
            keep = ("assets",)

        elif operation == "duration":
            seconds = float(payload.get("seconds") or 0)
            if not 4 <= seconds <= 120:
                raise ValueError("duration must be between 4 and 120 seconds")
            request = dict(project.request)
            request["duration_seconds"] = seconds
            project.request = request
            intent["duration_seconds"] = seconds
            project.put("intent", intent)
            decision = director.direct(project, intent)
            project.put("concept", decision["concept"])
            project.put("brief", decision["brief"])
            project.put("hooks", decision["hooks"])
            project.put("beats", decision["beats"])

        elif operation == "sound":
            seo = dict(project.get("seo") or {})
            sound = dict(seo.get("sound") or {})
            sound["mood"] = payload.get("mood") or sound.get("mood", "ambient")
            seo["sound"] = sound
            project.put("seo", seo)
            project.snapshot("refine:sound")
            project.event("growth", f"Sound brief updated to '{sound['mood']}' — export stays silent")
            self.store.save(project)
            return project

        invalidated = project.invalidate(spec["invalidates"], keep_data=keep)
        project.snapshot(f"refine:{operation}")
        project.event("studio", f"Refinement '{spec['label']}' — recomputing {len(invalidated)} "
                                f"component(s): {', '.join(invalidated) or 'none'}")
        project.status = "running"
        self.store.save(project)
        return self.run(project, progress=progress, only=invalidated)


def _label(name: str) -> str:
    return {
        "intent": "Reading your idea",
        "media": "Looking at your image",
        "concept": "Choosing the strongest angle",
        "brief": "Writing the brief",
        "hooks": "Scoring the opening line",
        "beats": "Structuring the story",
        "cues": "Timing the captions",
        "visual_plan": "Designing the shots",
        "prompts": "Writing the prompts",
        "assets": "Creating the visuals",
        "script": "Writing the script",
        "storyboard": "Storyboarding",
        "edit": "Cutting the timeline",
        "render": "Rendering the video",
        "review": "Checking the result",
        "final_review": "Checking the result",
        "seo": "Preparing your post",
    }.get(name, name)


ORCHESTRATOR = Orchestrator()
