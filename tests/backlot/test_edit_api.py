from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backlot import server as server_mod
from backlot import state as state_mod


@pytest.fixture
def client(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "renders").mkdir()
    (project / "assets").mkdir()
    (project / "project.json").write_text(json.dumps({"project_id": "demo", "title": "Demo"}), encoding="utf-8")
    (project / "artifacts" / "edit_decisions.json").write_text(json.dumps({
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "cuts": [
            {"id": "a", "source": "take.mp4", "in_seconds": 0, "out_seconds": 2},
            {"id": "b", "source": "take.mp4", "in_seconds": 2, "out_seconds": 4},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR", __import__("os").path.normcase(str(projects.resolve())))

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as test_client:
        yield test_client, project


def test_edit_timeline_get_normalises_existing_decisions(client):
    test_client, _project = client
    response = test_client.get("/api/project/demo/edit-timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "1.0"
    assert body["revision"] == 0
    assert [segment["id"] for segment in body["segments"]] == ["a", "b"]


def test_edit_timeline_patch_persists_and_rejects_stale_revision(client):
    test_client, project = client
    response = test_client.patch("/api/project/demo/edit-timeline", json={
        "base_revision": 0,
        "operations": [{
            "op": "trim",
            "segment_id": "a",
            "source_in_seconds": 0.25,
            "source_out_seconds": 1.5,
        }],
    })
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    saved = json.loads((project / "artifacts" / "edit_timeline.json").read_text(encoding="utf-8"))
    assert saved["segments"][0]["source_in_seconds"] == 0.25

    conflict = test_client.patch("/api/project/demo/edit-timeline", json={"base_revision": 0, "operations": []})
    assert conflict.status_code == 409


def test_edit_timeline_rejects_unknown_operation(client):
    test_client, _project = client
    response = test_client.patch("/api/project/demo/edit-timeline", json={
        "base_revision": 0,
        "operations": [{"op": "delete_everything"}],
    })
    assert response.status_code == 400
