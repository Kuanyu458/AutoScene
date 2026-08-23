import json
from pathlib import Path

import jsonschema
import pytest

from lib.pipeline_loader import load_pipeline
from lib.checkpoint import read_checkpoint, write_checkpoint
from schemas.artifacts import ARTIFACT_NAMES, load_schema, validate_artifact
from tools.tool_registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[2]


def _capture_package() -> dict:
    return {
        "version": "1.0",
        "package_id": "recordly-product-demo",
        "backend": "recordly",
        "video": {
            "relative_path": "assets/video/recordly-product-demo.mp4",
            "format": "mp4",
            "sha256": "a" * 64,
            "duration_seconds": 12.0,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "has_audio": True,
        },
        "sidecars": [
            {
                "role": "cursor",
                "relative_path": "assets/video/recordly-product-demo.cursor.json",
                "sha256": "b" * 64,
            }
        ],
        "provenance": {
            "source_tool": "recordly_recorder",
            "source_tool_version": "0.1.0",
            "capture_mode": "external_ui",
            "source_sha256": "c" * 64,
            "originals_modified": False,
            "absolute_source_path_included": False,
            "upstream_version": "1.3.5-beta.2",
            "upstream_commit": "72e9724505e2498fd85754cfe69e02d8a69900a0",
            "normalized_from_format": "webm",
        },
        "privacy_review": {
            "status": "passed",
            "reviewed": True,
            "passed": True,
            "sensitive_regions": [
                {
                    "id": "private-notification-1",
                    "start_frame": 30,
                    "end_frame": 45,
                    "kind": "notification",
                    "action": "blur",
                    "resolved": True,
                    "normalized_bbox": {
                        "x": 0.7,
                        "y": 0.02,
                        "width": 0.28,
                        "height": 0.16,
                    },
                }
            ],
            "unresolved_count": 0,
            "redactions_verified": True,
        },
    }


def _final_review() -> dict:
    return {
        "version": "1.0",
        "output_path": "renders/final.mp4",
        "status": "pass",
        "checks": {
            "technical_probe": {
                "valid_container": True,
                "duration_seconds": 12,
                "resolution": "1920x1080",
                "fps": 30,
                "has_audio": True,
                "codec": "h264",
                "file_size_bytes": 1024,
                "issues": [],
            },
            "visual_spotcheck": {
                "frames_sampled": 12,
                "frame_paths": [],
                "black_frames_detected": False,
                "broken_overlays": False,
                "missing_assets": False,
                "unreadable_text": False,
                "issues": [],
            },
            "audio_spotcheck": {
                "narration_present": True,
                "music_present": False,
                "unexpected_silence": False,
                "clipping_detected": False,
                "mix_intelligible": True,
                "issues": [],
            },
            "promise_preservation": {
                "delivery_promise_honored": True,
                "renderer_family_used": "screen-demo",
                "render_runtime_used": "remotion",
                "runtime_swap_detected": False,
                "runtime_swap_check": "ok",
                "motion_ratio_actual": 1.0,
                "silent_downgrade_detected": False,
                "issues": [],
            },
            "subtitle_check": {
                "subtitles_expected": True,
                "subtitles_present": True,
                "coverage_ratio": 1.0,
                "timing_drift_detected": False,
                "issues": [],
            },
            "privacy": {
                "required": True,
                "source_package_ref": "artifacts/screen_capture_package.json",
                "reviewed_frames": 12,
                "sensitive_regions_detected": 1,
                "unresolved_sensitive_regions": 0,
                "redactions_verified": True,
                "passed": True,
                "issues": [],
            },
        },
        "issues_found": [],
        "recommended_action": "present_to_user",
    }


def test_screen_capture_package_is_registered_and_portable():
    assert "screen_capture_package" in ARTIFACT_NAMES
    validate_artifact("screen_capture_package", _capture_package())
    schema = load_schema("screen_capture_package")
    assert "directory containing screen_capture_package.json" in schema["description"]
    assert "directory containing screen_capture_package.json" in (
        schema["properties"]["video"]["properties"]["relative_path"]["description"]
    )


def test_screen_capture_package_round_trips_as_supplementary_idea_artifact(tmp_path: Path):
    write_checkpoint(
        tmp_path,
        "recordly-demo",
        "idea",
        "completed",
        {
            "brief": {
                "version": "1.0",
                "title": "Recordly product walkthrough",
                "hook": "See the workflow in one minute",
                "key_points": ["Capture", "Edit", "Publish"],
                "tone": "clear",
                "style": "clean-professional",
                "target_platform": "youtube",
                "target_duration_seconds": 60,
                "metadata": {"production_mode": "real_capture"},
            },
            "screen_capture_package": _capture_package(),
        },
        pipeline_type="screen-demo",
    )

    checkpoint = read_checkpoint(tmp_path, "recordly-demo", "idea")
    assert checkpoint is not None
    assert checkpoint["artifacts"]["screen_capture_package"]["backend"] == "recordly"


@pytest.mark.parametrize(
    ("relative_path", "sha256"),
    [
        ("/private/video.mp4", "a" * 64),
        ("C:\\Users\\demo\\video.mp4", "a" * 64),
        ("assets/../private/video.mp4", "a" * 64),
        ("assets/video/capture.webm", "a" * 64),
        ("assets/video/capture.mp4", "not-a-sha256"),
    ],
)
def test_screen_capture_package_rejects_nonportable_video(relative_path: str, sha256: str):
    package = _capture_package()
    package["video"]["relative_path"] = relative_path
    package["video"]["sha256"] = sha256

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("screen_capture_package", package)


def test_screen_capture_package_cannot_pass_with_unresolved_privacy():
    package = _capture_package()
    package["privacy_review"]["unresolved_count"] = 1
    package["privacy_review"]["sensitive_regions"][0]["resolved"] = False

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("screen_capture_package", package)


def test_recordly_ingest_emits_the_portable_schema_without_source_paths(
    tmp_path: Path, monkeypatch
):
    from tools.capture import recordly_recorder as recordly_module
    from tools.capture.recordly_recorder import RecordlyRecorder

    source = tmp_path / "explicit-recordly-export.mp4"
    source.write_bytes(b"fixture-mp4")
    output = tmp_path / "staged-package"
    monkeypatch.setattr(
        recordly_module,
        "_probe_media",
        lambda _path: {
            "duration_seconds": 3.0,
            "resolution": "1920x1080",
            "fps": 30.0,
            "video_codec": "h264",
            "has_audio": True,
            "audio_codec": "aac",
            "format_names": ["mp4"],
        },
    )

    result = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
        }
    )

    assert result.success
    assert result.data["ready_for_pipeline"] is True
    assert result.data["ready_for_publish"] is False
    package_path = output / recordly_module.PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    validate_artifact("screen_capture_package", package)
    serialized = json.dumps(package, sort_keys=True)
    assert str(source) not in serialized
    assert str(output) not in serialized
    assert package["privacy_review"]["status"] == "pending"


def test_final_review_accepts_verified_real_capture_privacy():
    validate_artifact("final_review", _final_review())


def test_final_review_keeps_privacy_optional_for_non_capture_pipelines():
    review = _final_review()
    del review["checks"]["privacy"]
    validate_artifact("final_review", review)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("passed", False),
        ("unresolved_sensitive_regions", 1),
        ("redactions_verified", False),
    ],
)
def test_passing_real_capture_review_requires_closed_privacy_gate(field: str, value):
    review = _final_review()
    review["checks"]["privacy"][field] = value

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("final_review", review)


def test_screen_demo_manifest_adds_recordly_without_changing_default_modes():
    manifest = load_pipeline("screen-demo")
    modes = {mode["name"]: mode for mode in manifest["production_modes"]}

    assert set(modes) == {"real_capture", "synthetic_terminal"}
    real_capture = modes["real_capture"]
    assert real_capture["required_tools"] == ["screen_capture_selector"]
    assert {"recordly_recorder", "screen_recorder", "cap_recorder"}.issubset(
        real_capture["optional_tools"]
    )

    stages = {stage["name"]: stage for stage in manifest["stages"]}
    assert "recordly_recorder" in stages["idea"]["tools_available"]
    assert "screen_capture_package" in stages["idea"]["optional_artifacts_in"]
    assert "screen_capture_package" in stages["compose"]["optional_artifacts_in"]
    assert "screen_capture_package" in stages["publish"]["optional_artifacts_in"]
    assert any(
        "unresolved_sensitive_regions" in item
        for item in stages["compose"]["review_focus"]
    )


def test_recordly_and_selector_are_discoverable_contracts():
    registry = ToolRegistry()
    registry.discover("tools")
    recordly = registry.get("recordly_recorder")
    selector = registry.get("screen_capture_selector")

    assert recordly is not None
    assert recordly.capability == "screen_capture"
    assert recordly.provider == "recordly"
    operations = set(recordly.input_schema["properties"]["operation"]["enum"])
    assert {"doctor", "setup_guide", "launch", "ingest", "verify"}.issubset(operations)

    assert selector is not None
    preferred = selector.input_schema["properties"]["preferred_provider"]["enum"]
    assert "recordly" in preferred
    assert selector.input_schema["properties"]["privacy_review"]["enum"] == [
        "pending",
        "passed",
        "blocked",
    ]
    for fallback_name in selector.fallback_tools:
        assert registry.get(fallback_name) is not None, (
            f"selector fallback {fallback_name!r} must be a registered tool name"
        )


def test_recordly_is_an_external_bridge_not_a_bundled_dependency():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    package_json = json.loads(
        (ROOT / "remotion-composer/package.json").read_text(encoding="utf-8")
    )
    node_dependencies = {
        **package_json.get("dependencies", {}),
        **package_json.get("devDependencies", {}),
    }

    assert "recordly" not in pyproject
    assert not any("recordly" in name.lower() for name in node_dependencies)
    assert not (ROOT / "vendor" / "Recordly").exists()
    assert not (ROOT / "third_party" / "Recordly").exists()


def test_screen_demo_directors_enforce_manual_capture_and_privacy_gate():
    director_paths = [
        ROOT / "skills/pipelines/screen-demo/executive-producer.md",
        ROOT / "skills/pipelines/screen-demo/idea-director.md",
        ROOT / "skills/pipelines/screen-demo/asset-director.md",
        ROOT / "skills/pipelines/screen-demo/compose-director.md",
        ROOT / "skills/pipelines/screen-demo/publish-director.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in director_paths)
    lowered = combined.lower()

    assert "recordly" in lowered
    assert "external recordly ui" in lowered
    assert "screencapturepackage@1.0" in lowered
    assert "unresolved_sensitive_regions=0" in lowered
    assert "privacy.passed=true" in lowered
    assert "undocumented" in lowered and "export" in lowered
    assert "awaiting_human" in lowered
