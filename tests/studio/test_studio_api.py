"""Contract tests for OpenMontage Studio (the web frontend over this repo).

These exercise the real FastAPI app and the real repository tools — no mocks of
the tool registry. Generation providers are not configured in CI, so the tests
assert the *documented degradation*: labelled placeholder art, a real MP4 on
disk, and schema-valid artifacts.

Run:  python -m pytest tests/studio -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from studio import jobs as store  # noqa: E402
from studio.app import app  # noqa: E402
from studio.motion import render_motion_video  # noqa: E402
from studio.repo_bridge import ensure_ffmpeg  # noqa: E402

FFMPEG = ensure_ffmpeg()
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg binary unavailable")


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _wait(client: TestClient, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"done", "failed"}:
            return payload
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# ---------------------------------------------------------------------------
# capability surface
# ---------------------------------------------------------------------------

def test_health_reports_ffmpeg(client: TestClient) -> None:
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert payload["service"] == "openmontage-studio"
    assert "available" in payload["ffmpeg"]


def test_index_serves_the_campaign_studio(client: TestClient) -> None:
    """The root is the four-system studio; the single-prompt tools live at /ui/classic.html."""
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "OpenMontage" in body
    assert "/ui/campaigns.js" in body
    assert "data-nav=\"create\"" in body


def test_classic_tools_still_served(client: TestClient) -> None:
    response = client.get("/ui/classic.html")
    assert response.status_code == 200
    assert 'id="composerForm"' in response.text
    assert "/ui/app.js" in response.text


def test_static_assets(client: TestClient) -> None:
    for path in ("/ui/app.js", "/ui/campaigns.js", "/ui/styles.css", "/ui/campaigns.css"):
        assert client.get(path).status_code == 200, path


def test_presets_come_from_the_repo(client: TestClient) -> None:
    payload = client.get("/api/presets").json()
    aspect_ids = {a["id"] for a in payload["aspects"]}
    assert {"16:9", "9:16", "1:1"} <= aspect_ids
    motions = {m["id"] for m in payload["motions"]}
    assert {"ken_burns", "zoom_in", "pan_left", "static"} <= motions
    style_ids = {s["id"] for s in payload["styles"]}
    assert "clean-professional" in style_ids  # read from styles/*.yaml


def test_catalog_reflects_the_tool_registry(client: TestClient) -> None:
    payload = client.get("/api/catalog").json()
    assert payload["tool_count"] > 100  # the real registry, not a mock
    assert set(payload["capabilities"]) == {"image_generation", "video_generation", "tts"}
    for entry in payload["capabilities"].values():
        assert entry["total"] >= entry["configured"]
    assert isinstance(payload["unlock"], dict)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

@requires_ffmpeg
def test_image_job_writes_a_png_and_an_artifact(client: TestClient) -> None:
    response = client.post(
        "/api/images",
        json={"prompt": "studio contract test: a paper lantern over still water", "count": 2, "aspect": "4:5"},
    )
    assert response.status_code == 200
    job = _wait(client, response.json()["id"])

    assert job["status"] == "done", job.get("error")
    assert len(job["assets"]) == 2
    for asset in job["assets"]:
        path = Path(asset["path"])
        assert path.exists() and path.stat().st_size > 0
        assert (asset["width"], asset["height"]) == (1080, 1350)
        assert asset["provenance"] in {"model", "placeholder"}

    project = Path(job["project_dir"])
    brief = json.loads((project / "artifacts" / "brief.json").read_text())
    assert brief["title"] == job["prompt"][:80]
    assert brief["style"] == job["style"]
    assert brief["target_platform"] == "instagram"  # 4:5
    manifest = json.loads((project / "artifacts" / "asset_manifest.json").read_text())
    assert manifest["version"] == "1.0"
    assert len(manifest["assets"]) == 2


@requires_ffmpeg
def test_video_from_text_produces_a_real_mp4(client: TestClient) -> None:
    response = client.post(
        "/api/videos/from-text",
        json={
            "prompt": "studio contract test: terraced fields at golden hour",
            "aspect": "16:9",
            "duration_seconds": 3,
            "motion": "zoom_in",
            "count": 1,
        },
    )
    assert response.status_code == 200
    job = _wait(client, response.json()["id"])

    assert job["status"] == "done", job.get("error")
    video = job["video"]
    assert video and Path(video["path"]).exists()
    assert video["width"] == 1920 and video["height"] == 1080
    assert 2.0 <= video["duration_seconds"] <= 4.5
    assert video["bytes"] > 10_000
    assert video["poster_url"]

    project = Path(job["project_dir"])
    report = json.loads((project / "artifacts" / "render_report.json").read_text())
    assert report["outputs"][0]["resolution"] == "1920x1080"

    # media route serves it, with range support for the browser player
    media = client.get(video["url"])
    assert media.status_code == 200
    partial = client.get(video["url"], headers={"Range": "bytes=0-1023"})
    assert partial.status_code == 206


@requires_ffmpeg
def test_video_from_uploaded_image(client: TestClient, tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    source = tmp_path / "source.png"
    image = Image.new("RGB", (900, 1600), (18, 26, 40))
    ImageDraw.Draw(image).ellipse([250, 600, 650, 1000], fill=(224, 84, 46))
    image.save(source)

    with open(source, "rb") as handle:
        response = client.post(
            "/api/videos/from-image",
            files={"file": ("source.png", handle, "image/png")},
            data={"prompt": "slow push in", "aspect": "9:16", "duration_seconds": "3", "motion": "zoom_out"},
        )
    assert response.status_code == 200, response.text
    job = _wait(client, response.json()["id"])

    assert job["status"] == "done", job.get("error")
    assert job["video"]["width"] == 1080 and job["video"]["height"] == 1920
    assert job["assets"][0]["provenance"] == "upload"


def test_upload_rejects_non_images(client: TestClient) -> None:
    response = client.post(
        "/api/videos/from-image",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
        data={"prompt": "", "aspect": "16:9"},
    )
    assert response.status_code == 400
    assert "image type" in response.json()["detail"]


def test_requests_are_validated(client: TestClient) -> None:
    assert client.post("/api/images", json={"prompt": ""}).status_code == 422
    bad_aspect = client.post("/api/videos/from-text", json={"prompt": "x", "aspect": "7:3"})
    assert bad_aspect.status_code == 400
    bad_motion = client.post(
        "/api/videos/from-text", json={"prompt": "x", "motion": "dolly_zoom"}
    )
    assert bad_motion.status_code == 400
    too_long = client.post(
        "/api/videos/from-text", json={"prompt": "x", "duration_seconds": 900}
    )
    assert too_long.status_code == 422


def test_job_listing_and_delete(client: TestClient) -> None:
    listing = client.get("/api/jobs").json()
    assert "jobs" in listing and "stats" in listing
    assert client.get("/api/jobs/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# security
# ---------------------------------------------------------------------------

def test_media_route_blocks_path_traversal(client: TestClient) -> None:
    for attempt in (
        "/media/projects/../../etc/passwd",
        "/media/projects/%2e%2e/%2e%2e/etc/passwd",
        "/media/projects/../.env",
        "/media/uploads/../../.env",
    ):
        response = client.get(attempt)
        assert response.status_code == 404, attempt


def test_key_names_are_validated(client: TestClient) -> None:
    from studio.repo_bridge import save_keys

    result = save_keys({"lowercase": "x", "HAS SPACE": "y", "OKO_KEY": "z\nEVIL=1"})
    assert "OKO_KEY" not in result["saved"]
    assert set(result["rejected"]) == {"lowercase", "HAS SPACE", "OKO_KEY"}


# ---------------------------------------------------------------------------
# the studio pipeline manifest + checkpoints
# ---------------------------------------------------------------------------

def test_studio_pipeline_manifest_is_valid() -> None:
    from lib.pipeline_loader import get_stage_order, load_pipeline

    manifest = load_pipeline("studio")
    assert get_stage_order(manifest) == ["idea", "assets", "compose"]
    stages = {s["name"]: s for s in manifest["stages"]}
    assert stages["idea"]["produces"] == ["brief"]
    assert stages["assets"]["produces"] == ["asset_manifest"]
    assert stages["compose"]["produces"] == ["render_report"]
    assert stages["compose"]["skill"] == "pipelines/studio/compose-director"


@requires_ffmpeg
def test_run_writes_checkpoints_the_board_can_read(client: TestClient) -> None:
    response = client.post(
        "/api/videos/from-text",
        json={"prompt": "studio checkpoint test", "aspect": "1:1", "duration_seconds": 2, "count": 1},
    )
    job = _wait(client, response.json()["id"])
    assert job["status"] == "done", job.get("error")

    project = Path(job["project_dir"])
    for stage in ("idea", "assets", "compose"):
        path = project / f"checkpoint_{stage}.json"
        assert path.exists(), f"missing checkpoint_{stage}.json"
        payload = json.loads(path.read_text())
        assert payload["stage"] == stage
        assert payload["status"] == "completed"
        assert payload["pipeline_type"] == "studio"

    # The board's own state builder must understand the project.
    from backlot.state import load_board_state

    state = load_board_state(project)
    assert state["pipeline"]["known"] is True
    assert [s["name"] for s in state["stages"]] == ["idea", "assets", "compose"]
    assert all(s["status"] == "completed" for s in state["stages"])
    assert state["media"]["renders"]


# ---------------------------------------------------------------------------
# motion renderer (unit)
# ---------------------------------------------------------------------------

@requires_ffmpeg
def test_render_motion_video_moves_a_still(tmp_path: Path) -> None:
    from PIL import Image

    source = tmp_path / "still.png"
    Image.new("RGB", (640, 360), (20, 30, 45)).save(source)
    out = tmp_path / "clip.mp4"

    info = render_motion_video([source], out, preset="ken_burns", aspect="16:9", total_seconds=2)
    assert out.exists() and out.stat().st_size > 1000
    assert info["width"] == 1920 and info["height"] == 1080

    from studio.motion import probe

    probed = probe(out)
    assert probed["has_video"] is True
    assert 1.5 <= probed["duration_seconds"] <= 2.6


@requires_ffmpeg
def test_render_motion_video_crossfades_multiple_stills(tmp_path: Path) -> None:
    from PIL import Image

    stills = []
    for index, colour in enumerate([(30, 40, 60), (60, 30, 30)]):
        path = tmp_path / f"still_{index}.png"
        Image.new("RGB", (480, 480), colour).save(path)
        stills.append(path)

    out = tmp_path / "montage.mp4"
    render_motion_video(stills, out, preset="pan_right", aspect="1:1", total_seconds=2, crossfade=0.5)
    assert out.exists() and out.stat().st_size > 1000

    from studio.motion import probe

    assert probe(out)["width"] == 1080


def test_render_motion_video_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        render_motion_video([tmp_path / "nope.png"], tmp_path / "out.mp4")


def test_placeholder_poster_is_deterministic(tmp_path: Path) -> None:
    from studio.motion import demo_poster

    first = demo_poster("same prompt", tmp_path / "a.png", width=480, height=270)
    second = demo_poster("same prompt", tmp_path / "b.png", width=480, height=270)
    assert first.exists() and second.exists()
    assert first.read_bytes() == second.read_bytes()  # same seed -> same bytes


def test_placeholder_uses_playbook_palette() -> None:
    from studio.motion import playbook_palette

    palette = playbook_palette("flat-motion-graphics")
    assert palette[0].lower() == "#7c3aed"  # straight from styles/flat-motion-graphics.yaml


# ---------------------------------------------------------------------------
# restart recovery
# ---------------------------------------------------------------------------

def test_interrupted_jobs_are_reconciled_on_load(tmp_path: Path, monkeypatch) -> None:
    """A run cut off by a server restart must not stay "running" forever.

    Studio is single-process, so a persisted queued/running job cannot still be
    working; load() marks it failed with a reason the UI can show.
    """
    from studio import jobs as store

    payload = {
        "version": 1,
        "jobs": [
            {
                "id": "stuck00001",
                "kind": "video_from_text",
                "prompt": "interrupted run",
                "status": "running",
                "steps": [
                    {"name": "provider", "status": "done", "detail": ""},
                    {"name": "motion", "status": "running", "detail": ""},
                ],
            },
            {
                "id": "finished02",
                "kind": "image",
                "prompt": "already done",
                "status": "done",
                "steps": [{"name": "done", "status": "done", "detail": ""}],
            },
        ],
    }
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(store, "JOBS_PATH", jobs_path)
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_order", [])

    store.load()

    stuck = store.get("stuck00001")
    assert stuck is not None
    assert stuck.status == "failed"
    assert "Interrupted" in (stuck.error or "")
    assert stuck.steps[1].status == "failed"
    assert stuck.steps[0].status == "done"  # completed work is preserved

    untouched = store.get("finished02")
    assert untouched is not None and untouched.status == "done"

    persisted = json.loads(jobs_path.read_text())["jobs"]
    by_id = {j["id"]: j for j in persisted}
    assert by_id["stuck00001"]["status"] == "failed"
    assert by_id["finished02"]["status"] == "done"
