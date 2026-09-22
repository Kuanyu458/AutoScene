from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backlot import server as server_mod
from backlot import state as state_mod


def test_editor_page_is_served_for_valid_project(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "demo"
    project.mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR", __import__("os").path.normcase(str(projects.resolve())))

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as client:
        response = client.get("/p/demo/edit")
    assert response.status_code == 200
    assert "Timeline authoring" in response.text


def test_board_exposes_edit_artifacts_and_timeline_link(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo","title":"Demo"}', encoding="utf-8")
    (project / "artifacts" / "edit_decisions.json").write_text(json.dumps({
        "version": "1.0",
        "cuts": [{"id": "a", "source": "take.mp4", "in_seconds": 0, "out_seconds": 1}],
    }), encoding="utf-8")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR", __import__("os").path.normcase(str(projects.resolve())))

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as client:
        state = client.get("/api/project/demo/state")
        board = client.get("/p/demo")
    assert state.status_code == 200
    assert "edit_decisions" in state.json()["artifacts"]
    assert board.status_code == 200
    board_script = (server_mod.UI_DIR / "board.js").read_text(encoding="utf-8")
    assert "EDIT TIMELINE" in board_script
    assert 'href: "/p/" + encodedProjectId + "/edit"' in board_script
