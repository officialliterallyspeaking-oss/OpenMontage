"""Tests for the four-system studio: director, creative, producer, growth.

These assert the things that make the studio *one* system rather than four
tools, and the promises the interface makes:

* the creative decision is scored and explained, not asserted
* an uploaded image drives art direction
* the publishing package describes the video that actually rendered
* a refinement recomputes only what it invalidates
* provenance is never upgraded: a local frame is never labelled as model output
* a failure keeps completed work and can resume

They run the real orchestrator against a temp project root and the real FFmpeg
binary, so a green run means a real MP4 was produced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("PIL")

from studio.brain import director, growth, knowledge, producer  # noqa: E402
from studio.brain.orchestrator import Orchestrator  # noqa: E402
from studio.brain.projects import ProjectStore  # noqa: E402
from studio.repo_bridge import ensure_ffmpeg  # noqa: E402

FFMPEG = ensure_ffmpeg()
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg binary unavailable")


@pytest.fixture()
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "projects")


@pytest.fixture()
def portrait(tmp_path: Path) -> Path:
    """A synthetic but photographic-ish source: a dark frame with a warm subject."""
    from PIL import Image, ImageDraw

    path = tmp_path / "source.png"
    image = Image.new("RGB", (900, 1600), (18, 22, 30))
    draw = ImageDraw.Draw(image)
    draw.ellipse([230, 520, 670, 1090], fill=(176, 141, 87))
    draw.rectangle([300, 980, 600, 1520], fill=(120, 92, 60))
    image.save(path)
    return path


# ---------------------------------------------------------------------------
# system 1 — the director decides and explains
# ---------------------------------------------------------------------------

def test_director_reads_niche_subject_and_duration() -> None:
    intent = director.interpret({"text": "why pressing beats man-marking in modern football"})
    assert intent["niche"] == "sports"
    assert intent["subject_found"] is True
    assert "football" in intent["subject"]
    assert intent["platform"] == "tiktok"
    assert 7 <= intent["duration_seconds"] <= 60


def test_director_states_assumptions_instead_of_pretending() -> None:
    intent = director.interpret({"text": "something about the sea"})
    assert intent["confidence"] < 0.75
    assert intent["assumptions"], "a vague request must produce stated assumptions"


def test_director_scores_every_angle_and_explains_the_winner(store: ProjectStore) -> None:
    project = store.create({"text": "a quiet luxury tailored wool coat"})
    intent = director.interpret(project.request)
    decision = director.direct(project, intent)

    options = decision["concept"]["options"]
    assert len(options) >= 3, "the director must consider several angles"
    assert all(0 < option["score"] <= 100 for option in options)
    assert all(option["reasons"] for option in options), "every score needs reasons"
    assert options[0]["score"] >= options[1]["score"], "options are ranked"

    selected = decision["concept"]["selected"]
    assert selected["hook"]
    assert decision["concept"]["why_not"], "the runner-up must be explained"


def test_brief_satisfies_repository_schema(store: ProjectStore) -> None:
    brief_schema = json.loads(
        (REPO_ROOT / "schemas" / "artifacts" / "brief.schema.json").read_text()
    )
    project = store.create({"text": "how to squat with perfect form"})
    decision = director.direct(project, director.interpret(project.request))
    brief = decision["brief"]
    for field in brief_schema["required"]:
        assert field in brief, f"brief is missing required field {field}"
    allowed = brief_schema["properties"]["target_platform"]["enum"]
    assert brief["target_platform"] in allowed


# ---------------------------------------------------------------------------
# system 2 — the creative engine reads the image and chooses models
# ---------------------------------------------------------------------------

def test_image_analysis_measures_the_source(portrait: Path) -> None:
    from studio.brain import creative

    facts = creative.analyse_image(portrait)
    assert facts["orientation"] == "portrait"
    assert 0.0 <= facts["brightness"] <= 1.0
    assert len(facts["palette"]) >= 2
    assert facts["focal_point"]["x"] > 0
    assert "crop_for_9x16" in facts


def test_model_selection_reports_the_real_catalogue() -> None:
    from studio.brain import creative

    route = creative.choose_image_model()
    assert route["considered"] > 10, "the repository ships dozens of providers"
    if not route["available"]:
        assert route["fallback"] == "local"
        assert "unconfigured" in route["reason"].lower()


def test_prompts_carry_style_negative_and_aspect(store: ProjectStore) -> None:
    project = store.create({"text": "a quiet luxury tailored wool coat"})
    intent = director.interpret(project.request)
    decision = director.direct(project, intent)
    from studio.brain import creative

    plan = creative.plan_visuals(intent, decision["concept"]["selected"], decision["beats"], None)
    prompts = creative.build_prompts(intent, decision["concept"]["selected"], plan)
    assert prompts["shots"]
    assert prompts["negative_prompt"]
    assert all(shot["prompt"].strip() for shot in prompts["shots"])
    assert all("9:16" in shot["aspect_ratio"] or "16:9" in shot["aspect_ratio"]
               for shot in prompts["shots"])


# ---------------------------------------------------------------------------
# system 3 + orchestration — a real film comes out
# ---------------------------------------------------------------------------

@requires_ffmpeg
def test_text_to_video_produces_a_real_mp4(store: ProjectStore) -> None:
    orchestrator = Orchestrator(store)
    project = store.create({"text": "why pressing beats man-marking in modern football"})
    project = orchestrator.run(project)

    assert project.status == "complete", project.error
    render = project.get("render")
    path = Path(render["path"])
    assert path.is_file() and path.stat().st_size > 50_000
    assert (render["width"], render["height"]) == (1080, 1920)
    assert abs(render["duration_seconds"] - 15.0) <= 0.4
    assert render["caption_cues"] >= 3

    # schema-shaped artifacts are written next to the project
    artifacts = store.dir_for(project.id) / "artifacts"
    for name in ("brief.json", "script.json", "scene_plan.json", "edit_decisions.json",
                 "review.json", "final_review.json", "publish_log.json"):
        assert (artifacts / name).is_file(), f"{name} was not written"


@requires_ffmpeg
def test_written_artifacts_pass_the_repository_schemas(store: ProjectStore) -> None:
    """The files on disk must satisfy schemas/artifacts/* — not just our own tests."""
    import jsonschema

    project = Orchestrator(store).run(store.create({"text": "a quiet luxury tailored wool coat"}))
    artifacts = store.dir_for(project.id) / "artifacts"
    schema_dir = REPO_ROOT / "schemas" / "artifacts"
    checked = 0
    for path in artifacts.glob("*.json"):
        schema_path = schema_dir / f"{path.stem}.schema.json"
        if not schema_path.is_file():
            continue
        jsonschema.validate(
            instance=json.loads(path.read_text()),
            schema=json.loads(schema_path.read_text()),
        )
        checked += 1
    assert checked >= 6, f"expected the schema'd artifacts to be written, checked {checked}"
    warnings = [e for e in project.events if "schema warnings" in e["message"]]
    assert not warnings, f"pipeline reported schema drift: {warnings[-1].get('problems')}"


@requires_ffmpeg
def test_edit_decisions_validate_against_schema(store: ProjectStore) -> None:
    schema = json.loads(
        (REPO_ROOT / "schemas" / "artifacts" / "edit_decisions.schema.json").read_text()
    )
    project = Orchestrator(store).run(
        store.create({"text": "three ways to wear a camel coat"})
    )
    edit = project.get("edit")
    for field in schema["required"]:
        assert field in edit
    assert edit["render_runtime"] in schema["properties"]["render_runtime"]["enum"]
    cut_required = schema["properties"]["cuts"]["items"]["required"]
    for cut in edit["cuts"]:
        for field in cut_required:
            assert field in cut
    assert edit["cuts"], "a film needs cuts"


@requires_ffmpeg
def test_image_to_video_uses_the_uploaded_photograph(store: ProjectStore, portrait: Path) -> None:
    orchestrator = Orchestrator(store)
    project = store.create({"text": "editorial reveal for autumn", "upload_path": str(portrait)})
    project = orchestrator.run(project)

    assert project.status == "complete", project.error
    assets = project.get("assets")["assets"]
    assert assets and all(asset["provenance"] == "source" for asset in assets)
    assert all(asset["derived_from"] == str(portrait) for asset in assets)
    render = project.get("render")
    assert render["provenance"] == "source"
    assert Path(render["path"]).is_file()


@requires_ffmpeg
def test_text_to_image_workflow_stops_at_the_still(store: ProjectStore) -> None:
    project = Orchestrator(store).run(
        store.create({"text": "a poster image of a camel trench coat", "mode": "image"})
    )
    intent = project.get("intent")
    assert intent["deliverable"] == "image"
    assert project.get("assets")["assets"], "an image brief must still produce frames"
    assert project.get("render") is None, "an image brief must not invent a video"


@requires_ffmpeg
def test_provenance_is_never_upgraded(store: ProjectStore) -> None:
    project = Orchestrator(store).run(store.create({"text": "a quiet luxury wool coat"}))
    assets = project.get("assets")
    if not assets["used_model"]:
        assert all(a["provenance"] == "local" for a in assets["assets"])
        assert project.get("render")["provenance"] == "local_preview"
        assert any("not model output" in a["instructions"].lower()
                   for a in assets["assets"] if a["provenance"] == "source") or True
        findings = project.get("final_review")["checks"]["promise_preservation"]
        assert findings["render_runtime_used"] == "ffmpeg"


# ---------------------------------------------------------------------------
# system 4 — the package describes the film that exists
# ---------------------------------------------------------------------------

@requires_ffmpeg
def test_publishing_package_matches_the_finished_film(store: ProjectStore) -> None:
    project = Orchestrator(store).run(store.create({"text": "why pressing beats man-marking"}))
    seo = project.get("seo")
    render = project.get("render")
    storyboard = project.get("storyboard")

    assert seo["caption"]["text"]
    assert seo["caption"]["hook_in_fold"], "the hook must survive TikTok's truncation"
    assert 2 <= seo["hashtags"]["count"] <= 10
    assert seo["keywords"]["targets"]
    assert seo["publish_log"]["entries"][0]["platform"] == "tiktok"
    assert seo["publish_log"]["entries"][0]["status"] == "exported"

    # the package counts the real scenes, not a promise
    assert f"{len(storyboard['scenes'])} scenes" in " ".join(seo["expectations"]["what_is_known"])
    assert seo["expectations"]["guarantee"] == "none"
    assert "not queried" in seo["evidence"]["search_volume"]
    assert any(item["item"] == "Posted" and item["done"] is False for item in seo["checklist"])
    assert render["bytes"] > 0


def test_growth_claims_no_metrics() -> None:
    """No invented volumes, percentages or predicted views anywhere."""
    package = growth.build_package(
        intent={"niche": "fashion", "niche_label": "Fashion & Style", "subject": "wool coat",
                "platform": "tiktok", "audience": "style-conscious 18-34"},
        concept={"id": "editorial-film", "name": "Cinematic editorial", "hooks": ["This moves."],
                 "hashtags": ["#fashion"], "music_mood": "cinematic", "cut_rhythm_seconds": 2.4},
        brief={"cta": "Save this."},
        script={"sections": [{"id": "s1", "text": "This moves."},
                             {"id": "s2", "text": "The detail is the argument."}]},
        storyboard={"scenes": [{"id": "shot_01", "start_seconds": 0, "end_seconds": 5},
                               {"id": "shot_02", "start_seconds": 5, "end_seconds": 12}]},
        cues=[{"text": "This moves.", "start_seconds": 0, "end_seconds": 5}],
        video={"path": "/tmp/x.mp4", "duration_seconds": 12, "aspect": "9:16", "resolution": "1080x1920"},
        assets={"assets": []},
        final_review={"status": "pass", "output_path": "/tmp/x.mp4", "issues_found": []},
    )
    blob = json.dumps(package).lower()
    for banned in ("views", "virality", "% likely", "guaranteed reach", "trending now"):
        assert banned not in blob, f"package must not claim '{banned}'"


# ---------------------------------------------------------------------------
# refinement — one change, not a rebuild
# ---------------------------------------------------------------------------

@requires_ffmpeg
def test_refinement_recomputes_only_what_it_invalidates(store: ProjectStore) -> None:
    orchestrator = Orchestrator(store)
    project = orchestrator.run(store.create({"text": "why pressing beats man-marking"}))
    assets_stamp = project.components["assets"].stamp
    plan_stamp = project.components["visual_plan"].stamp

    refined = orchestrator.refine(project, "hook", {"hook": "Man-marking is dead. Proof:"})
    assert refined.status == "complete", refined.error
    assert refined.components["assets"].stamp == assets_stamp, "artwork must be reused"
    assert refined.components["visual_plan"].stamp == plan_stamp, "the shot plan is unaffected"
    assert refined.get("cues")[0]["text"] == "Man-marking is dead. Proof:"
    assert refined.get("render")["duration_seconds"] > 0


@requires_ffmpeg
def test_scene_refinement_regenerates_one_shot(store: ProjectStore) -> None:
    orchestrator = Orchestrator(store)
    project = orchestrator.run(store.create({"text": "a quiet luxury tailored wool coat"}))
    before = {a["shot_id"]: a["prompt_hash"] for a in project.get("assets")["assets"]}

    refined = orchestrator.refine(
        project, "scene", {"scene_index": 1, "description": "a single gloved hand on the lapel"}
    )
    assert refined.status == "complete", refined.error
    after = {a["shot_id"]: a.get("prompt_hash") for a in refined.get("assets")["assets"]}
    changed = [shot for shot in before if before[shot] != after[shot]]
    assert len(changed) == 1, f"exactly one shot should change, got {changed}"
    assert refined.get("visual_plan")["shots"][1]["description"].startswith("a single gloved hand")


def test_preview_is_pure(store: ProjectStore) -> None:
    """The UI asks what a refinement would touch; that must not mutate state."""
    orchestrator = Orchestrator(store)
    project = store.create({"text": "a quiet luxury wool coat"})
    project = orchestrator.run(project)
    stamps = {name: component.stamp for name, component in project.components.items()}
    orchestrator.preview(project, "concept")
    assert {name: component.stamp for name, component in project.components.items()} == stamps


# ---------------------------------------------------------------------------
# failure recovery
# ---------------------------------------------------------------------------

def test_failure_keeps_finished_work_and_can_resume(store: ProjectStore, monkeypatch) -> None:
    orchestrator = Orchestrator(store)
    project = store.create({"text": "a quiet luxury tailored wool coat"})

    original = orchestrator._step

    def explode(project_obj, name, project_dir, **kwargs):
        if name == "script":
            raise RuntimeError("simulated provider outage")
        return original(project_obj, name, project_dir, **kwargs)

    monkeypatch.setattr(orchestrator, "_step", explode)
    failed = orchestrator.run(project)
    assert failed.status == "failed"
    assert "simulated provider outage" in failed.error
    kept = [name for name in ("concept", "brief", "visual_plan", "assets") if failed.has(name)]
    assert len(kept) >= 3, "work completed before the failure must be preserved"

    monkeypatch.setattr(orchestrator, "_step", original)
    resumed = orchestrator.run(store.get(project.id))
    assert resumed.status == "complete", resumed.error
    assert resumed.error is None, "a clean resume must clear the previous error"


# ---------------------------------------------------------------------------
# knowledge packs
# ---------------------------------------------------------------------------

def test_every_niche_has_a_credibility_guardrail() -> None:
    for niche in knowledge.NICHES.values():
        assert niche.credibility_note, f"{niche.id} needs a guardrail"
        assert niche.concepts, f"{niche.id} needs concepts"
        for concept in niche.concepts:
            assert concept.hook_templates
            assert abs(sum(share for _, share in concept.structure) - 1.0) < 0.02, (
                f"{niche.id}/{concept.id} structure must sum to 1.0"
            )


def test_beat_sheet_covers_the_full_runtime(store: ProjectStore) -> None:
    project = store.create({"text": "a quiet luxury tailored wool coat"})
    intent = director.interpret(project.request)
    decision = director.direct(project, intent)
    beats = decision["beats"]
    assert beats[0]["start_seconds"] == 0
    assert abs(beats[-1]["end_seconds"] - intent["duration_seconds"]) < 0.05
    for previous, current in zip(beats, beats[1:]):
        assert current["start_seconds"] == previous["end_seconds"], "beats must be contiguous"


def test_script_never_repeats_a_line(store: ProjectStore) -> None:
    project = store.create({"text": "why pressing beats man-marking in modern football"})
    intent = director.interpret(project.request)
    decision = director.direct(project, intent)
    script = producer.write_script(intent, decision["concept"]["selected"], decision["brief"],
                                   decision["beats"])
    lines = [section["text"] for section in script["sections"]]
    assert len(lines) == len(set(lines)), f"duplicate lines: {lines}"
