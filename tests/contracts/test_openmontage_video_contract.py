"""Contracts for the dedicated openmontage-video skill and pipeline."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from lib.pipeline_loader import get_required_tools, load_pipeline
from lib.checkpoint import init_project, write_checkpoint
from schemas.artifacts import validate_artifact


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / ".agents" / "skills" / "openmontage-video" / "scripts" / "validate-job.py"


def _validator_module():
    spec = importlib.util.spec_from_file_location("openmontage_validate_job", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _job(**overrides):
    job = {
        "version": "1.0",
        "project_id": "fixture-product",
        "source": {"mode": "provided", "media": [{"path": "assets/demo.mp4", "media_type": "video"}]},
        "recording": {"base_url": "http://127.0.0.1:8000", "allowed_origins": [], "flows": []},
        "music": {"mode": "provided", "path": "assets/music/fixture.wav"},
        "features": {"beat_sync": "required", "ui_3d": "required", "ui_capture": "required"},
        "edit": {"snap_tolerance_ms": 250, "focus_budget_per_scene": 1, "focus_scale": [1.2, 1.35]},
        "approvals": {"mode": "guided"},
        "output": {"resolution": "1920x1080", "fps": 30, "language": "zh-TW"},
    }
    for key, value in overrides.items():
        job[key] = value
    return job


def test_pipeline_manifest_and_directors_are_complete():
    manifest = load_pipeline("openmontage-video")
    assert manifest["name"] == "openmontage-video"
    assert {mode["name"] for mode in manifest["production_modes"]} == {"provided", "record", "mixed"}
    assert get_required_tools(manifest) >= {"audio_timing", "video_compose", "playwright_recorder"}
    for stage in manifest["stages"]:
        assert stage.get("skill")
        assert (ROOT / "skills" / f"{stage['skill']}.md").is_file()


def test_feature_artifacts_validate():
    validate_artifact("audiomap", {"version": "1.0", "status": "not_applicable"})
    validate_artifact(
        "rights_privacy_review",
        {
            "version": "1.0",
            "status": "awaiting_human",
            "checks": {"rights": "unknown", "privacy": "pass", "origins": "pass", "credentials": "pass"},
        },
    )
    validate_artifact(
        "rough_cut_report",
        {"version": "1.0", "status": "awaiting_human", "output_path": "rough.mp4", "duration_seconds": 12, "changes": [], "known_issues": []},
    )
    validate_artifact(
        "feature_evidence",
        {
            "version": "1.0",
            "features": {
                "beat_sync": {"status": "pass", "evidence": ["audiomap.json"]},
                "ui_3d": {"status": "pass", "evidence": ["hyperframes-inspect.json"]},
                "ui_capture": {"status": "pass", "evidence": ["capture.mp4"]},
            },
        },
    )


def test_edit_automation_contract_carries_focus_and_3d_evidence():
    validate_artifact(
        "edit_decisions",
        {
            "version": "1.0",
            "cuts": [{"id": "cut-1", "source": "capture.mp4", "in_seconds": 0, "out_seconds": 4}],
            "render_runtime": "hyperframes",
            "automation": {
                "beat_sync": {"enabled": True, "audiomap_path": "artifacts/audiomap.json", "snap_tolerance_ms": 250},
                "ui_focus_events": [{"scene_id": "ui-1", "focus_count": 1, "scale": 1.25, "event": "click"}],
                "ui_3d_scenes": [{"scene_id": "depth-1", "planes": 2, "perspective": 1400, "translate_z": [0, 80], "motion_direction": "forward", "no_global_shake": True}],
            },
        },
    )


def test_job_validator_defaults_features_and_rejects_secrets():
    validator = _validator_module()
    normalized = validator.validate_job(_job())
    assert normalized["features"] == {"beat_sync": "required", "ui_3d": "required", "ui_capture": "required"}
    with pytest.raises(validator.JobValidationError, match="credential"):
        validator.validate_job({**_job(), "metadata": {"api_key": "sk-secret-value-123456"}})


def test_job_validator_modes_and_allowlist():
    validator = _validator_module()
    with pytest.raises(validator.JobValidationError, match="recording.flows"):
        validator.validate_job({**_job(), "source": {"mode": "record", "media": []}})
    with pytest.raises(validator.JobValidationError, match="allowed_origins"):
        validator.validate_job({**_job(), "recording": {"base_url": "https://demo.example", "allowed_origins": [], "flows": [{"name": "x", "steps": [{"op": "goto", "url": "/"}]}]}, "source": {"mode": "record", "media": []}})
    with pytest.raises(validator.JobValidationError, match="decision"):
        validator.validate_job({**_job(), "features": {"beat_sync": "off", "ui_3d": "required", "ui_capture": "required"}})
    with pytest.raises(validator.JobValidationError, match="Recordly"):
        validator.validate_job({**_job(), "source": {"mode": "provided", "media": [{"path": "capture.recordly", "media_type": "recordly_export"}]}})


def test_explicit_autonomous_job_can_advance_manifest_gate(tmp_path):
    project_dir = init_project("autonomous-fixture", title="Fixture", pipeline_type="openmontage-video", pipeline_dir=tmp_path)
    job = _job(project_id="autonomous-fixture")
    job["approvals"] = {"mode": "autonomous"}
    job["metadata"] = {"autonomous_authorization": True}
    (project_dir / "job.yaml").write_text(yaml.safe_dump(job, sort_keys=False), encoding="utf-8")
    write_checkpoint(
        tmp_path,
        "autonomous-fixture",
        "idea",
        "completed",
        {
            "brief": {
                "version": "1.0",
                "title": "Fixture",
                "hook": "A clear hook",
                "key_points": ["proof"],
                "tone": "professional",
                "style": "clean-professional",
                "target_platform": "youtube",
                "target_duration_seconds": 30,
            }
        },
        pipeline_type="openmontage-video",
    )
