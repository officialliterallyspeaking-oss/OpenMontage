"""Shared fixtures for Studio tests.

The Studio keeps its job index in ``studio_state/jobs.json`` — the file the web
UI reads. A test run must never write there, or contract-test runs show up in the
user's gallery. Every test therefore gets a private, empty job index.

Project workspaces are deliberately *not* redirected: the media route resolves
paths against the real ``projects/`` root, and asserting that served media works
is part of the contract. Project dirs are gitignored scratch output.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def isolated_job_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the Studio job index to a per-test temp directory."""
    from studio import jobs as store

    jobs_path = tmp_path / "studio_state" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(store, "STATE_DIR", jobs_path.parent)
    monkeypatch.setattr(store, "JOBS_PATH", jobs_path)
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_order", [])

    yield store

    # Nothing a test creates may survive into the next test.
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_order", [])
