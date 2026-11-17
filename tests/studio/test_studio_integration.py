"""The two integrations: recipes reach the plan, the plan reaches the NLE.

Unit tests prove each piece works on its own. These prove the studio actually
*uses* them — a recipe catalogue nothing consults is a document, and a timeline
writer nothing calls is a library.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from studio.brain import creative, recipes  # noqa: E402

from studio.repo_bridge import ensure_ffmpeg  # noqa: E402

requires_ffmpeg = pytest.mark.skipif(not ensure_ffmpeg(), reason="ffmpeg binary unavailable")


# --------------------------------------------------------------------------- #
# recipes -> visual plan
# --------------------------------------------------------------------------- #

@pytest.fixture()
def built() -> dict:
    """A concept from the director, not a hand-written dict.

    A stub concept would keep passing after the real one grew a field, and the
    integration would break in production instead of here.
    """
    from studio.brain import director
    from studio.brain.projects import Project

    request = {"text": "the quiet luxury of a tailored wool coat", "platform": "tiktok"}
    intent = director.interpret(request, None)
    project = Project(id="fixture", title="fixture", request=request)
    decision = director.direct(project, intent)
    # the selected concept already carries its own hooks; the separate `hooks`
    # component is a dict of options and is not what plan_visuals reads
    return {"intent": intent, "concept": decision["concept"]["selected"],
            "beats": decision["beats"]}


@pytest.fixture()
def plan(built: dict) -> dict:
    return creative.plan_visuals(built["intent"], built["concept"], built["beats"], None)


def test_every_shot_carries_a_recipe_and_a_reason(plan: dict) -> None:
    for shot in plan["shots"]:
        recipe = shot.get("recipe")
        assert recipe, f"{shot['id']} has no recipe"
        assert recipe["id"] in recipes.BY_ID
        assert recipe["reason"]
        assert recipe["why"] and recipe["pitfall"]


def test_the_plan_reports_its_craft_at_the_top(plan: dict) -> None:
    craft = plan["craft"]
    assert craft["shot_count"] == len(plan["shots"])
    assert craft["distinct_devices"] == len(plan["shots"])
    assert craft["repeats"] == []
    assert craft["functions"][0] == "hook" and craft["functions"][-1] == "close"


def test_the_camera_move_comes_from_the_recipe_not_the_index(plan: dict) -> None:
    movements = [s["movement"] for s in plan["shots"]]
    recipe_moves = [s["recipe"]["movement"] for s in plan["shots"]]
    assert movements == recipe_moves


def test_the_recipe_changes_the_artwork_not_only_the_words(plan: dict) -> None:
    """Each shot must name a composition localfx can actually draw."""
    from studio.brain import localfx

    for shot in plan["shots"]:
        assert shot["recipe"]["composition"] in localfx.COMPOSITIONS_BY_NAME


def test_planning_the_same_brief_twice_gives_the_same_film(built: dict, plan: dict) -> None:
    again = creative.plan_visuals(built["intent"], dict(built["concept"]), built["beats"], None)
    assert [s["recipe"]["id"] for s in again["shots"]] == [s["recipe"]["id"] for s in plan["shots"]]


def test_named_composition_reaches_the_renderer(tmp_path: Path) -> None:
    """The whole point: a recipe name has to change pixels, not just JSON."""
    from studio.brain import localfx

    frames = {}
    for name in ("aperture", "plates"):
        out = tmp_path / f"{name}.jpg"
        localfx.design_frame(
            out, headline="the quiet luxury of a coat", kicker="Fashion",
            body="held in a patient wide frame", palette=["#2A2320", "#F2EDE4", "#C98B6B", "#8E9A7C"],
            width=540, height=960, variant=0, composition=name, label="LOCAL COMPOSITION",
        )
        frames[name] = out.read_bytes()
    assert frames["aperture"] != frames["plates"]


def test_an_unknown_composition_falls_back_instead_of_crashing(tmp_path: Path) -> None:
    from studio.brain import localfx

    out = tmp_path / "fallback.jpg"
    meta = localfx.design_frame(
        out, headline="fallback", kicker="Fashion", palette=["#2A2320", "#F2EDE4"],
        width=360, height=640, variant=2, composition="not-a-real-composition",
    )
    assert out.is_file() and meta["renderer"] == "studio.localfx.design_frame"


# --------------------------------------------------------------------------- #
# a finished project -> an editable timeline on disk
# --------------------------------------------------------------------------- #

@requires_ffmpeg
def test_a_real_project_writes_an_editable_timeline(tmp_path: Path) -> None:
    """Text prompt in, MP4 and a Premiere-ready timeline out."""
    from studio.brain.orchestrator import Orchestrator
    from studio.brain.projects import ProjectStore

    store = ProjectStore(tmp_path / "projects")
    project = Orchestrator(store).run(
        store.create({"text": "the quiet luxury of a tailored wool coat"})
    )
    assert project.status == "complete", project.error

    folder = store.dir_for(project.id) / "renders" / "timeline"
    for name in ("timeline.xml", "timeline.fcpxml", "timeline.edl", "timeline.json"):
        assert (folder / name).is_file(), f"{name} was not written"

    manifest = json.loads((folder / "timeline.json").read_text())
    checks = manifest["checks"]
    assert checks["clips"] >= 3
    assert checks["continuous"] is True, checks
    assert checks["holes"] == [] and checks["overlaps"] == []

    # the XML must open: it names the frame size and the clip count we audited
    xmeml = (folder / "timeline.xml").read_text()
    assert "<xmeml" in xmeml and "1080" in xmeml and "1920" in xmeml
    assert xmeml.count("<clipitem") >= checks["clips"]

    # and the project says so, rather than the UI having to guess
    assert any("editable timeline" in event["message"] for event in project.events)


def test_the_timeline_is_not_written_for_a_failed_project(tmp_path: Path) -> None:
    """A half-finished project must not ship a timeline of missing media."""
    from studio.brain.orchestrator import Orchestrator
    from studio.brain.projects import ProjectStore

    store = ProjectStore(tmp_path / "projects")
    project = store.create({"text": "a coat"})
    project.status = "failed"
    orchestrator = Orchestrator(store)
    assert orchestrator._write_timeline(project, store.dir_for(project.id)) is None


# --------------------------------------------------------------------------- #
# the API surface a browser actually calls
# --------------------------------------------------------------------------- #

def test_the_edit_payload_is_absent_until_a_timeline_exists(tmp_path: Path) -> None:
    """No file, no button: the UI must not point at something that is not there."""
    from studio.brain.projects import ProjectStore
    from studio.api_projects import _edit_payload

    store = ProjectStore(tmp_path / "projects")
    project = store.create({"text": "a coat"})
    assert _edit_payload(project) is None


def test_the_edit_payload_lists_the_formats_that_are_on_disk(tmp_path: Path) -> None:
    from studio.brain.projects import ProjectStore
    import studio.api_projects as api

    store = ProjectStore(tmp_path / "projects")
    project = store.create({"text": "a coat"})
    folder = store.dir_for(project.id) / "renders" / "timeline"
    folder.mkdir(parents=True)
    (folder / "timeline.xml").write_text("<xmeml/>")
    (folder / "timeline.json").write_text(json.dumps({
        "formats": {"premiere_resolve": "timeline.xml", "final_cut": "timeline.fcpxml"},
        "checks": {"clips": 3, "continuous": True},
    }))

    original = api._store
    api._store = lambda: store
    try:
        payload = api._edit_payload(project)
    finally:
        api._store = original

    # the fcpxml is declared but was never written, so it is not offered
    assert payload["formats"] == {"premiere_resolve": "timeline.xml"}
    assert payload["download"]["premiere_resolve"].endswith("/edit/timeline.xml")
    assert payload["checks"]["continuous"] is True


def test_a_corrupt_manifest_is_not_an_error_page(tmp_path: Path) -> None:
    from studio.brain.projects import ProjectStore
    import studio.api_projects as api

    store = ProjectStore(tmp_path / "projects")
    project = store.create({"text": "a coat"})
    folder = store.dir_for(project.id) / "renders" / "timeline"
    folder.mkdir(parents=True)
    (folder / "timeline.json").write_text("{ not json")

    original = api._store
    api._store = lambda: store
    try:
        assert api._edit_payload(project) is None
    finally:
        api._store = original
