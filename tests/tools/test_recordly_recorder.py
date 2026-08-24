import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from schemas.artifacts import validate_artifact
from tools.base_tool import ToolStatus
from tools.capture import recordly_recorder as recordly_module
from tools.capture.recordly_recorder import (
    PACKAGE_FILENAME,
    STAGED_MEDIA_RELATIVE_PATH,
    UPSTREAM_COMMIT,
    RecordlyRecorder,
)


@pytest.fixture
def media_probe(monkeypatch):
    metadata = {
        "duration_seconds": 4.0,
        "width": 1920,
        "height": 1080,
        "resolution": "1920x1080",
        "fps": 30.0,
        "video_codec": "h264",
        "has_audio": True,
        "audio_codec": "aac",
        "format_names": ["mov", "mp4"],
    }
    monkeypatch.setattr(recordly_module, "_probe_media", lambda _path: dict(metadata))
    return metadata


def _make_fake_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "Recordly"
    executable.write_bytes(b"fake-recordly-executable")
    return executable


def _make_source_mp4(tmp_path: Path, content: bytes = b"recordly-mp4-fixture") -> Path:
    source = tmp_path / "recordly-export.mp4"
    source.write_bytes(content)
    return source


def _mark_package_passed(output: Path) -> dict:
    package_path = output / PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["privacy_review"] = {
        "status": "passed",
        "reviewed": True,
        "passed": True,
        "sensitive_regions": [],
        "unresolved_count": 0,
        "redactions_verified": True,
    }
    validate_artifact("screen_capture_package", package)
    package_path.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return package


def test_get_status_separates_app_detection_from_ingest_readiness(monkeypatch, tmp_path: Path):
    executable = _make_fake_executable(tmp_path)
    monkeypatch.setattr(recordly_module, "_find_recordly_executable", lambda *args, **kwargs: None)
    monkeypatch.setattr(recordly_module.shutil, "which", lambda command: "/usr/bin/ffprobe" if command == "ffprobe" else None)
    assert RecordlyRecorder().get_status() == ToolStatus.DEGRADED

    monkeypatch.setattr(
        recordly_module,
        "_find_recordly_executable",
        lambda *args, **kwargs: executable,
    )
    assert RecordlyRecorder().get_status() == ToolStatus.AVAILABLE

    monkeypatch.setattr(recordly_module.shutil, "which", lambda _command: None)
    assert RecordlyRecorder().get_status() == ToolStatus.UNAVAILABLE


def test_executable_detection_uses_exact_paths_without_treating_any_directory_as_app(
    tmp_path: Path,
):
    directory = tmp_path / "not-an-app"
    directory.mkdir()

    assert recordly_module._resolve_explicit_executable(directory) == directory.resolve()
    assert recordly_module._find_recordly_executable(directory) is None
    linux_candidates = recordly_module._known_executable_candidates("Linux")
    assert any(path.name == "Recordly.AppImage" for path in linux_candidates)
    assert any(path.name == "Recordly-linux-x64.AppImage" for path in linux_candidates)


def test_doctor_reports_optional_external_bridge_without_claiming_permissions(
    monkeypatch, tmp_path: Path
):
    executable = _make_fake_executable(tmp_path)
    monkeypatch.setattr(
        recordly_module.shutil,
        "which",
        lambda command: "/usr/bin/ffprobe" if command == "ffprobe" else None,
    )

    result = RecordlyRecorder().execute(
        {"operation": "doctor", "application_path": str(executable)}
    )

    assert result.success
    assert result.data["installed"] is True
    assert result.data["ingest_ready"] is True
    assert result.data["stable_external_automation"] is False
    assert result.data["automation_level"] == "user_guided"
    assert result.data["private_smoke_api_used"] is False
    assert result.data["upstream_commit"] == UPSTREAM_COMMIT
    assert all(item["status"] == "unknown" for item in result.data["required_permissions"])


def test_setup_guide_keeps_recordly_external_and_attributed(monkeypatch):
    monkeypatch.setattr(recordly_module, "_find_recordly_executable", lambda *args, **kwargs: None)

    result = RecordlyRecorder().execute({"operation": "setup_guide"})

    assert result.success
    assert result.data["integration_mode"] == "external_optional_gui_bridge"
    assert result.data["license"] == "AGPL-3.0"
    assert "webadderallorg/Recordly" in result.data["download_url"]
    assert "separate" in result.data["attribution"].lower()


def test_launch_only_opens_gui_and_returns_awaiting_human(monkeypatch, tmp_path: Path):
    executable = _make_fake_executable(tmp_path)
    calls = []

    class FakeProcess:
        pid = 4242

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(recordly_module.subprocess, "Popen", fake_popen)

    result = RecordlyRecorder().execute(
        {"operation": "launch", "application_path": str(executable)}
    )

    assert result.success
    assert result.data["capture_state"] == "awaiting_human"
    assert result.data["launcher_pid"] == 4242
    assert result.data["privacy_review"] == "pending"
    assert calls and str(executable) in calls[0][0]
    assert "input_path" not in result.data


def test_ingest_copies_without_mutating_source_and_writes_portable_package(
    tmp_path: Path, media_probe
):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "package"
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_mtime = source.stat().st_mtime_ns

    result = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "pending",
        }
    )

    assert result.success
    assert result.data["ready_for_pipeline"] is True
    assert result.data["ready_for_publish"] is False
    assert result.data["status"] == "pending"
    assert result.data["media_relative_path"] == STAGED_MEDIA_RELATIVE_PATH
    assert source.read_bytes() == source_bytes
    assert source.stat().st_mtime_ns == source_mtime
    assert result.data["source_sha256"] == source_hash
    assert result.data["staged_sha256"] == source_hash

    staged = output / STAGED_MEDIA_RELATIVE_PATH
    package_path = output / PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    serialized_package = package_path.read_text(encoding="utf-8")
    assert staged.read_bytes() == source_bytes
    validate_artifact("screen_capture_package", package)
    assert package["version"] == "1.0"
    assert package["backend"] == "recordly"
    assert package["video"]["relative_path"] == STAGED_MEDIA_RELATIVE_PATH
    assert package["video"]["format"] == "mp4"
    assert package["privacy_review"]["status"] == "pending"
    assert package["privacy_review"]["reviewed"] is False
    assert package["privacy_review"]["passed"] is False
    assert package["provenance"]["upstream_commit"] == UPSTREAM_COMMIT
    assert package["provenance"]["originals_modified"] is False
    assert package["provenance"]["absolute_source_path_included"] is False
    assert str(source) not in serialized_package
    assert str(staged) not in serialized_package

    verified = RecordlyRecorder().execute({"operation": "verify", "output_dir": str(output)})
    assert verified.success
    assert verified.data["status"] == "pending"
    assert verified.data["ready_for_pipeline"] is True
    assert verified.data["ready_for_publish"] is False


def test_ingest_cannot_self_assert_a_passed_privacy_review(tmp_path: Path, media_probe):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "unreviewed-package"

    result = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "passed",
        }
    )

    assert not result.success
    assert "PRIVACY_REVIEW_EVIDENCE_REQUIRED" in result.error
    assert result.data["ready_for_pipeline"] is False
    assert result.data["ready_for_publish"] is False
    assert not output.exists()


def test_ingest_privacy_blocked_creates_nothing(tmp_path: Path, media_probe):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "blocked-package"

    result = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "blocked",
        }
    )

    assert not result.success
    assert "PRIVACY_REVIEW_BLOCKED" in result.error
    assert result.data["privacy_review"] == "blocked"
    assert result.data["ready_for_pipeline"] is False
    assert result.data["ready_for_publish"] is False
    assert not output.exists()


def test_ingest_refuses_non_mp4_and_existing_output(tmp_path: Path, media_probe):
    source = tmp_path / "capture.webm"
    source.write_bytes(b"webm")
    result = RecordlyRecorder().execute(
        {"operation": "ingest", "input_path": str(source), "output_dir": str(tmp_path / "one")}
    )
    assert not result.success
    assert "INPUT_NOT_MP4" in result.error

    mp4 = _make_source_mp4(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    result = RecordlyRecorder().execute(
        {"operation": "ingest", "input_path": str(mp4), "output_dir": str(output)}
    )
    assert not result.success
    assert "OUTPUT_NOT_EMPTY" in result.error
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_ingest_never_overwrites_a_completed_package(tmp_path: Path, media_probe):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "package"
    tool = RecordlyRecorder()
    first = tool.execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "pending",
        }
    )
    package_bytes = (output / PACKAGE_FILENAME).read_bytes()
    staged_bytes = (output / STAGED_MEDIA_RELATIVE_PATH).read_bytes()

    second = tool.execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "pending",
        }
    )

    assert first.success
    assert not second.success
    assert "OUTPUT_NOT_EMPTY" in second.error
    assert (output / PACKAGE_FILENAME).read_bytes() == package_bytes
    assert (output / STAGED_MEDIA_RELATIVE_PATH).read_bytes() == staged_bytes


def test_ingest_failure_preserves_a_preexisting_empty_output_directory(
    tmp_path: Path, media_probe, monkeypatch
):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "existing-empty"
    output.mkdir()

    def fail_copy(_source, _destination):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(recordly_module.shutil, "copy2", fail_copy)
    result = RecordlyRecorder().execute(
        {"operation": "ingest", "input_path": str(source), "output_dir": str(output)}
    )

    assert not result.success
    assert output.is_dir()
    assert list(output.iterdir()) == []


def test_verify_uses_relative_media_path_after_package_moves(tmp_path: Path, media_probe):
    source = _make_source_mp4(tmp_path)
    original_output = tmp_path / "original-package"
    ingest = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(original_output),
            "privacy_review": "pending",
        }
    )
    assert ingest.success
    _mark_package_passed(original_output)

    moved_output = tmp_path / "moved-package"
    original_output.rename(moved_output)
    result = RecordlyRecorder().execute(
        {"operation": "verify", "output_dir": str(moved_output)}
    )

    assert result.success
    assert result.data["status"] == "passed"
    assert result.data["ready_for_pipeline"] is True
    assert result.data["ready_for_publish"] is True
    assert result.data["media_path"] == str(moved_output / STAGED_MEDIA_RELATIVE_PATH)


def test_verify_detects_tampering_and_path_escape(tmp_path: Path, media_probe):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "package"
    ingest = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "pending",
        }
    )
    assert ingest.success
    _mark_package_passed(output)

    staged = output / STAGED_MEDIA_RELATIVE_PATH
    staged.write_bytes(b"tampered")
    result = RecordlyRecorder().execute({"operation": "verify", "output_dir": str(output)})
    assert not result.success
    assert "MEDIA_HASH_MISMATCH" in result.error

    staged.write_bytes(source.read_bytes())
    package_path = output / PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["video"]["relative_path"] = "../recordly-export.mp4"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    result = RecordlyRecorder().execute({"operation": "verify", "output_dir": str(output)})
    assert not result.success
    assert "PACKAGE_SCHEMA_INVALID" in result.error


@pytest.mark.parametrize(
    ("mutator", "expected_error"),
    [
        (lambda package: package["video"].update({"width": 1280}), "MEDIA_METADATA_MISMATCH"),
        (lambda package: package.update({"backend": "cap"}), "PACKAGE_PROVENANCE_INVALID"),
    ],
)
def test_verify_rejects_probe_or_provenance_drift(
    tmp_path: Path, media_probe, mutator, expected_error
):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "drift-package"
    ingest = RecordlyRecorder().execute(
        {"operation": "ingest", "input_path": str(source), "output_dir": str(output)}
    )
    assert ingest.success
    package_path = output / PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    mutator(package)
    validate_artifact("screen_capture_package", package)
    package_path.write_text(json.dumps(package), encoding="utf-8")

    result = RecordlyRecorder().execute({"operation": "verify", "output_dir": str(output)})

    assert not result.success
    assert expected_error in result.error


def test_verify_blocks_a_package_marked_blocked(tmp_path: Path, media_probe):
    source = _make_source_mp4(tmp_path)
    output = tmp_path / "package"
    ingest = RecordlyRecorder().execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(output),
            "privacy_review": "pending",
        }
    )
    assert ingest.success

    package_path = output / PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["privacy_review"]["status"] = "blocked"
    validate_artifact("screen_capture_package", package)
    package_path.write_text(json.dumps(package), encoding="utf-8")
    result = RecordlyRecorder().execute({"operation": "verify", "output_dir": str(output)})

    assert not result.success
    assert result.data["status"] == "blocked"
    assert result.data["ready_for_pipeline"] is False
    assert result.data["ready_for_publish"] is False
    assert "PRIVACY_REVIEW_BLOCKED" in result.error


def test_ffprobe_contract_validates_mp4_and_extracts_stream_metadata(monkeypatch, tmp_path: Path):
    source = _make_source_mp4(tmp_path)
    payload = {
        "format": {"duration": "2.500000", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30000/1001",
            },
            {"index": 1, "codec_type": "audio", "codec_name": "aac"},
        ],
    }
    monkeypatch.setattr(
        recordly_module.shutil,
        "which",
        lambda command: "/usr/bin/ffprobe" if command == "ffprobe" else None,
    )
    monkeypatch.setattr(
        recordly_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )

    result = recordly_module._probe_media(source)

    assert result["duration_seconds"] == 2.5
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["resolution"] == "1920x1080"
    assert result["fps"] == pytest.approx(29.97003)
    assert result["video_codec"] == "h264"
    assert result["audio_codec"] == "aac"


def test_adapter_source_has_no_private_smoke_api_or_home_scan():
    source = Path(recordly_module.__file__).read_text(encoding="utf-8")
    forbidden_tokens = [
        "RECORDLY_SMOKE_EXPORT",
        "RECORDLY_DEV_OPEN_RECORDING_INPUT",
        "Path.home(",
        ".glob(",
        ".rglob(",
        "userData",
    ]
    assert all(token not in source for token in forbidden_tokens)
