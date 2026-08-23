"""Optional external Recordly GUI bridge.

Recordly is treated as a separately installed desktop application.  This
adapter deliberately does not vendor Recordly, call its private Electron IPC,
depend on its smoke-test environment variables, or search its user-data
directory.  A human records and exports in Recordly; OpenMontage then ingests
an explicitly selected MP4 into a project-owned, portable package.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from jsonschema.exceptions import SchemaError, ValidationError

from schemas.artifacts import validate_artifact
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


UPSTREAM_REPOSITORY = "https://github.com/webadderallorg/Recordly"
UPSTREAM_COMMIT = "72e9724505e2498fd85754cfe69e02d8a69900a0"
UPSTREAM_VERSION = "1.3.5-beta.2"
PACKAGE_FILENAME = "screen_capture_package.json"
STAGED_MEDIA_RELATIVE_PATH = "media/recordly-capture.mp4"
PRIVACY_REVIEW_STATUSES = {"pending", "passed", "blocked"}
SUPPORTED_PLATFORMS = {"Darwin", "Windows", "Linux"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_explicit_executable(path_value: str | os.PathLike[str]) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.suffix.lower() == ".app":
        candidate = candidate / "Contents" / "MacOS" / "Recordly"
    return candidate.resolve()


def _known_executable_candidates(system: str) -> list[Path]:
    """Return exact install locations only; never enumerate user directories."""
    candidates: list[Path] = []

    configured = os.environ.get("OPENMONTAGE_RECORDLY_PATH", "").strip()
    if configured:
        candidates.append(_resolve_explicit_executable(configured))

    if system == "Darwin":
        candidates.append(Path("/Applications/Recordly.app/Contents/MacOS/Recordly"))
    elif system == "Windows":
        for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(variable, "").strip()
            if not base:
                continue
            if variable == "LOCALAPPDATA":
                candidates.append(Path(base) / "Programs" / "Recordly" / "Recordly.exe")
            candidates.append(Path(base) / "Recordly" / "Recordly.exe")
    elif system == "Linux":
        candidates.extend(
            [
                Path("/opt/Recordly/recordly"),
                Path("/usr/local/bin/recordly"),
                Path("/usr/bin/recordly"),
                Path("~/Applications/Recordly.AppImage"),
                Path("~/Applications/Recordly-linux-x64.AppImage"),
            ]
        )

    for command in ("Recordly", "recordly"):
        resolved = shutil.which(command)
        if resolved:
            candidates.append(Path(resolved))

    # Preserve order while removing duplicates.  resolve(strict=False) keeps
    # this read-only even when a candidate does not exist.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.expanduser().resolve(strict=False))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(Path(normalized))
    return unique


def _find_recordly_executable(
    explicit_path: str | os.PathLike[str] | None = None,
    *,
    system: str | None = None,
) -> Path | None:
    candidates = (
        [_resolve_explicit_executable(explicit_path)]
        if explicit_path
        else _known_executable_candidates(system or platform.system())
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _read_application_version(executable: Path | None, system: str) -> str | None:
    """Read package metadata without launching Recordly or trusting --version."""
    if executable is None or system != "Darwin":
        return None
    info_plist = executable.parent.parent / "Info.plist"
    if not info_plist.is_file():
        return None
    try:
        with info_plist.open("rb") as handle:
            payload = plistlib.load(handle)
        value = payload.get("CFBundleShortVersionString")
        return str(value).strip() if value else None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def _fraction_to_float(value: Any) -> float | None:
    if not isinstance(value, str) or value in {"", "0/0", "N/A"}:
        return None
    try:
        result = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return round(result, 6) if result > 0 else None


def _probe_media(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFPROBE_UNAVAILABLE: install FFmpeg before ingesting Recordly media")

    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or ["unknown ffprobe error"]
        raise RuntimeError(f"FFPROBE_FAILED: {detail[0]}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FFPROBE_INVALID_JSON: ffprobe returned malformed metadata") from exc

    format_info = payload.get("format") if isinstance(payload, dict) else None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(format_info, dict) or not isinstance(streams, list):
        raise RuntimeError("INVALID_MEDIA: ffprobe did not return format and stream metadata")

    format_names = {
        part.strip().lower()
        for part in str(format_info.get("format_name", "")).split(",")
        if part.strip()
    }
    if "mp4" not in format_names:
        raise RuntimeError("INPUT_NOT_MP4: Recordly ingest requires an MP4 container")

    video_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise RuntimeError("INVALID_MEDIA: MP4 has no video stream")

    try:
        duration = float(format_info.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise RuntimeError("INVALID_MEDIA: MP4 duration must be greater than zero")

    audio_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
        None,
    )
    fps = _fraction_to_float(video_stream.get("avg_frame_rate")) or _fraction_to_float(
        video_stream.get("r_frame_rate")
    )
    width = video_stream.get("width")
    height = video_stream.get("height")
    resolution = (
        f"{width}x{height}"
        if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0
        else "unknown"
    )

    return {
        "duration_seconds": round(duration, 6),
        "width": width if isinstance(width, int) and width > 0 else None,
        "height": height if isinstance(height, int) and height > 0 else None,
        "resolution": resolution,
        "fps": fps,
        "video_codec": video_stream.get("codec_name"),
        "has_audio": audio_stream is not None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "format_names": sorted(format_names),
    }


def _path_within(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("PACKAGE_PATH_INVALID: media.relative_path must be relative")
    resolved_root = root.resolve()
    resolved_candidate = (resolved_root / relative_path).resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("PACKAGE_PATH_INVALID: media path escapes package directory") from exc
    return resolved_candidate


def _metadata_mismatches(
    declared: dict[str, Any], actual: dict[str, Any]
) -> list[str]:
    """Return package fields that disagree with a fresh ffprobe result."""
    mismatches: list[str] = []
    for field in ("width", "height", "has_audio"):
        if field in declared and declared[field] != actual.get(field):
            mismatches.append(field)
    for field, tolerance in (("duration_seconds", 0.001), ("fps", 0.001)):
        if field not in declared:
            continue
        try:
            difference = abs(float(declared[field]) - float(actual.get(field)))
        except (TypeError, ValueError):
            mismatches.append(field)
            continue
        if difference > tolerance:
            mismatches.append(field)
    return mismatches


class RecordlyRecorder(BaseTool):
    """Bridge a human-operated Recordly capture into an OpenMontage project."""

    name = "recordly_recorder"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "screen_capture"
    provider = "recordly"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = (
        "Install Recordly from its official GitHub releases page: "
        f"{UPSTREAM_REPOSITORY}/releases. Recordly remains a separate AGPLv3 desktop "
        "application; OpenMontage does not bundle it."
    )
    # Capture policy is defined by the Layer 2 screen-demo directors; there is
    # no matching Layer 3 skill pointer for this external human-operated app.

    capabilities = [
        "recordly_doctor",
        "recordly_setup_guidance",
        "launch_recordly_gui",
        "ingest_explicit_recordly_mp4",
        "verify_screen_capture_package",
    ]
    best_for = [
        "Human-guided product UI capture with Recordly's cursor, zoom, webcam, and frame tools",
        "Copying a completed Recordly MP4 into a portable OpenMontage project",
    ]
    not_good_for = [
        "Headless or fully automated screen recording",
        "Controlling Recordly through private Electron IPC or smoke-test interfaces",
        "Discovering recordings by scanning a user's home or Recordly user-data directory",
    ]
    supports = {
        "capture_mode": "external_optional_gui",
        "headless": False,
        "automated_recording": False,
        "portable_ingest": True,
        "input_container": "mp4",
    }
    resource_profile = ResourceProfile(
        cpu_cores=1,
        ram_mb=128,
        vram_mb=0,
        disk_mb=1024,
        network_required=False,
    )
    side_effects = ["launches_external_gui", "creates_files"]
    fallback_tools = ["screen_recorder", "cap_recorder"]
    user_visible_verification = [
        "Source SHA-256 is identical before and after ingest",
        "Staged MP4 SHA-256 matches the source",
        "ffprobe confirms an MP4 video stream with positive duration",
        "Package media is resolved by a project-relative path",
        "Privacy review state is explicit: pending, passed, or blocked",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["doctor", "setup_guide", "launch", "ingest", "verify"],
            },
            "application_path": {
                "type": "string",
                "description": "Optional explicit Recordly executable or macOS .app path.",
            },
            "input_path": {
                "type": "string",
                "description": "Explicit MP4 exported by the user from Recordly (ingest only).",
            },
            "output_dir": {
                "type": "string",
                "description": "New or empty package directory for ingest/verify.",
            },
            "privacy_review": {
                "type": "string",
                "enum": ["pending", "blocked"],
                "default": "pending",
                "description": (
                    "Ingest creates a pending package. blocked aborts ingest; passed requires "
                    "a separate evidence-bearing privacy review and cannot be asserted here."
                ),
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "installed": {"type": "boolean"},
            "executable_path": {"type": ["string", "null"]},
            "capture_state": {"type": "string"},
            "package_path": {"type": "string"},
            "media_path": {"type": "string"},
            "media_relative_path": {"type": "string"},
            "privacy_review": {"type": "string"},
            "status": {"type": "string"},
            "ready_for_pipeline": {"type": "boolean"},
            "ready_for_publish": {"type": "boolean"},
        },
    }
    artifact_schema = {"artifact": "screen_capture_package", "version": "1.0"}

    def get_status(self) -> ToolStatus:
        executable = _find_recordly_executable()
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return ToolStatus.UNAVAILABLE
        if executable and ffprobe:
            return ToolStatus.AVAILABLE
        return ToolStatus.DEGRADED

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation")
        if operation == "doctor":
            return self._doctor(inputs)
        if operation == "setup_guide":
            return self._setup_guide()
        if operation == "launch":
            return self._launch(inputs)
        if operation == "ingest":
            return self._ingest(inputs)
        if operation == "verify":
            return self._verify(inputs)
        return ToolResult(
            success=False,
            error="INVALID_OPERATION: expected doctor, setup_guide, launch, ingest, or verify",
        )

    def _doctor(self, inputs: dict[str, Any]) -> ToolResult:
        system = platform.system()
        executable = _find_recordly_executable(inputs.get("application_path"), system=system)
        ffprobe = shutil.which("ffprobe")
        installed = executable is not None
        supported = system in SUPPORTED_PLATFORMS

        return ToolResult(
            success=True,
            data={
                "installed": installed,
                "executable_path": str(executable) if executable else None,
                "application_version": _read_application_version(executable, system),
                "platform": system,
                "platform_supported": supported,
                "ffprobe_available": ffprobe is not None,
                "ingest_ready": ffprobe is not None,
                "automation_level": "user_guided",
                "stable_external_automation": False,
                "capture_state": "ready" if installed and supported else "setup_required",
                "privacy_review": "pending",
                "required_permissions": self._required_permissions(system),
                "upstream_repository": UPSTREAM_REPOSITORY,
                "upstream_commit": UPSTREAM_COMMIT,
                "integration_mode": "external_optional_gui_bridge",
                "private_smoke_api_used": False,
                "message": (
                    "Recordly is installed. Recording remains a user-operated GUI step."
                    if installed
                    else "Recordly is not detected. Use setup_guide or pass application_path explicitly."
                ),
            },
        )

    def _setup_guide(self) -> ToolResult:
        system = platform.system()
        platform_steps = {
            "Darwin": {
                "minimum": "macOS 14.0",
                "artifact": "Recordly-<arm64|x64>.dmg",
                "permissions": self._required_permissions("Darwin"),
            },
            "Windows": {
                "minimum": "Windows 10 build 19041",
                "artifact": "Recordly-windows-<arch>.exe",
                "permissions": self._required_permissions("Windows"),
            },
            "Linux": {
                "minimum": "modern Linux distribution",
                "artifact": "Recordly-linux-x64.AppImage",
                "permissions": self._required_permissions("Linux"),
            },
        }
        return ToolResult(
            success=True,
            data={
                "installed": _find_recordly_executable(system=system) is not None,
                "platform": system,
                "setup": platform_steps.get(
                    system,
                    {"minimum": "unsupported platform", "artifact": None, "permissions": []},
                ),
                "download_url": f"{UPSTREAM_REPOSITORY}/releases",
                "source_code": UPSTREAM_REPOSITORY,
                "license": "AGPL-3.0",
                "attribution": "Recordly is a separate project by webadderallorg.",
                "trademark_note": "Recordly name and branding remain with the upstream project.",
                "integration_mode": "external_optional_gui_bridge",
                "next_step": (
                    "Run operation='launch', record and export an MP4 in Recordly, then call "
                    "operation='ingest' with that exact input_path."
                ),
            },
        )

    def _launch(self, inputs: dict[str, Any]) -> ToolResult:
        system = platform.system()
        executable = _find_recordly_executable(inputs.get("application_path"), system=system)
        if executable is None:
            return ToolResult(
                success=False,
                error="RECORDLY_NOT_FOUND: install Recordly or provide application_path",
            )
        if system not in SUPPORTED_PLATFORMS:
            return ToolResult(
                success=False,
                error=f"PLATFORM_UNSUPPORTED: Recordly integration does not support {system}",
            )

        command = [str(executable)]
        if system == "Darwin" and executable.parent.name == "MacOS":
            app_bundle = executable.parent.parent.parent
            if app_bundle.suffix.lower() == ".app" and shutil.which("open"):
                command = [shutil.which("open") or "open", "-a", str(app_bundle)]

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=system != "Windows",
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"LAUNCH_FAILED: {exc}")

        launched_at = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            success=True,
            data={
                "installed": True,
                "executable_path": str(executable),
                "capture_state": "awaiting_human",
                "launched_at": launched_at,
                "launcher_pid": process.pid,
                "automation_level": "user_guided",
                "privacy_review": "pending",
                "next_step": (
                    "Record and export an MP4 in Recordly. Then explicitly select it and call "
                    "operation='ingest'; OpenMontage will not scan Recordly's files."
                ),
            },
        )

    def _ingest(self, inputs: dict[str, Any]) -> ToolResult:
        input_value = inputs.get("input_path")
        output_value = inputs.get("output_dir")
        if not isinstance(input_value, str) or not input_value.strip():
            return ToolResult(success=False, error="INPUT_REQUIRED: ingest requires input_path")
        if not isinstance(output_value, str) or not output_value.strip():
            return ToolResult(success=False, error="OUTPUT_REQUIRED: ingest requires output_dir")

        privacy_status = inputs.get("privacy_review", "pending")
        if privacy_status not in PRIVACY_REVIEW_STATUSES:
            return ToolResult(
                success=False,
                error="PRIVACY_REVIEW_INVALID: expected pending, passed, or blocked",
            )
        if privacy_status == "blocked":
            return ToolResult(
                success=False,
                data={
                    "privacy_review": "blocked",
                    "ready_for_pipeline": False,
                    "ready_for_publish": False,
                },
                error="PRIVACY_REVIEW_BLOCKED: remove or redact sensitive capture content before ingest",
            )
        if privacy_status == "passed":
            return ToolResult(
                success=False,
                data={
                    "privacy_review": "pending",
                    "ready_for_pipeline": False,
                    "ready_for_publish": False,
                },
                error=(
                    "PRIVACY_REVIEW_EVIDENCE_REQUIRED: ingest cannot assert a passed review; "
                    "complete the frame-level privacy review after staging"
                ),
            )

        source = Path(input_value).expanduser().resolve()
        output_dir = Path(output_value).expanduser().resolve()
        package_path = output_dir / PACKAGE_FILENAME
        media_path = output_dir / STAGED_MEDIA_RELATIVE_PATH

        if not source.is_file():
            return ToolResult(success=False, error=f"INPUT_NOT_FOUND: {source}")
        if source.suffix.lower() != ".mp4":
            return ToolResult(success=False, error="INPUT_NOT_MP4: ingest requires an explicit MP4")
        if output_dir.exists() and any(output_dir.iterdir()):
            return ToolResult(
                success=False,
                error=f"OUTPUT_NOT_EMPTY: refusing to overwrite package directory {output_dir}",
            )
        if source == media_path.resolve(strict=False):
            return ToolResult(success=False, error="INPUT_OUTPUT_COLLISION: source is the staged path")

        try:
            source_stat_before = source.stat()
            source_hash_before = _sha256(source)
            media_info = _probe_media(source)
        except (OSError, RuntimeError) as exc:
            return ToolResult(success=False, error=str(exc))

        created_paths: list[Path] = []
        output_dir_preexisted = output_dir.exists()
        media_dir_preexisted = media_path.parent.exists()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            media_path.parent.mkdir(parents=True, exist_ok=True)
            if media_path.exists() or package_path.exists():
                raise FileExistsError("OUTPUT_EXISTS: refusing to overwrite staged media or package")

            shutil.copy2(source, media_path)
            created_paths.append(media_path)

            staged_hash = _sha256(media_path)
            source_hash_after = _sha256(source)
            source_stat_after = source.stat()
            source_unchanged = (
                source_hash_before == source_hash_after
                and source_stat_before.st_size == source_stat_after.st_size
                and source_stat_before.st_mtime_ns == source_stat_after.st_mtime_ns
            )
            if not source_unchanged:
                raise RuntimeError("SOURCE_CHANGED_DURING_INGEST: source hash or metadata changed")
            if staged_hash != source_hash_before:
                raise RuntimeError("COPY_HASH_MISMATCH: staged MP4 does not match the source")

            video = {
                "relative_path": STAGED_MEDIA_RELATIVE_PATH,
                "format": "mp4",
                "sha256": staged_hash,
                "duration_seconds": media_info["duration_seconds"],
                "has_audio": media_info["has_audio"],
            }
            for field in ("width", "height", "fps"):
                value = media_info.get(field)
                if value is not None:
                    video[field] = value

            package = {
                "version": "1.0",
                "package_id": f"recordly-{source_hash_before[:16]}",
                "backend": "recordly",
                "video": video,
                "privacy_review": {
                    "status": "pending",
                    "reviewed": False,
                    "passed": False,
                    "sensitive_regions": [],
                    "unresolved_count": 0,
                    "redactions_verified": False,
                },
                "provenance": {
                    "source_tool": self.name,
                    "source_tool_version": self.version,
                    "capture_mode": "external_ui",
                    "source_sha256": source_hash_before,
                    "originals_modified": False,
                    "absolute_source_path_included": False,
                    "upstream_version": UPSTREAM_VERSION,
                    "upstream_commit": UPSTREAM_COMMIT,
                    "normalized_from_format": "mp4",
                },
            }
            validate_artifact("screen_capture_package", package)
            with package_path.open("x", encoding="utf-8") as handle:
                json.dump(package, handle, indent=2, sort_keys=True)
                handle.write("\n")
            created_paths.append(package_path)
        except (OSError, RuntimeError, SchemaError, ValidationError) as exc:
            for created_path in reversed(created_paths):
                created_path.unlink(missing_ok=True)
            if not media_dir_preexisted:
                try:
                    media_path.parent.rmdir()
                except OSError:
                    pass
            if not output_dir_preexisted:
                try:
                    output_dir.rmdir()
                except OSError:
                    pass
            if isinstance(exc, (SchemaError, ValidationError)):
                return ToolResult(
                    success=False,
                    error=(
                        "PACKAGE_SCHEMA_INVALID: generated screen_capture_package does not "
                        "satisfy version 1.0"
                    ),
                )
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            data={
                "package_path": str(package_path),
                "media_path": str(media_path),
                "media_relative_path": STAGED_MEDIA_RELATIVE_PATH,
                "source_sha256": source_hash_before,
                "staged_sha256": staged_hash,
                "source_hash_unchanged": True,
                "capture_method": "recordly_external_gui",
                "privacy_review": "pending",
                "status": "pending",
                "ready_for_pipeline": True,
                "ready_for_publish": False,
            },
            artifacts=[str(media_path), str(package_path)],
        )

    def _verify(self, inputs: dict[str, Any]) -> ToolResult:
        output_value = inputs.get("output_dir")
        if not isinstance(output_value, str) or not output_value.strip():
            return ToolResult(success=False, error="OUTPUT_REQUIRED: verify requires output_dir")

        output_dir = Path(output_value).expanduser().resolve()
        package_path = output_dir / PACKAGE_FILENAME
        if not package_path.is_file():
            return ToolResult(success=False, error=f"PACKAGE_NOT_FOUND: {package_path}")

        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=f"PACKAGE_INVALID_JSON: {exc}")
        if not isinstance(package, dict):
            return ToolResult(success=False, error="PACKAGE_SCHEMA_INVALID: expected an object")
        try:
            validate_artifact("screen_capture_package", package)
        except (SchemaError, ValidationError):
            return ToolResult(
                success=False,
                error=(
                    "PACKAGE_SCHEMA_INVALID: screen_capture_package does not satisfy version 1.0"
                ),
            )

        provenance = package.get("provenance")
        if (
            package.get("backend") != "recordly"
            or not isinstance(provenance, dict)
            or provenance.get("source_tool") != self.name
            or provenance.get("capture_mode") != "external_ui"
            or provenance.get("upstream_commit") != UPSTREAM_COMMIT
        ):
            return ToolResult(
                success=False,
                error="PACKAGE_PROVENANCE_INVALID: expected Recordly external-bridge provenance",
            )

        media = package.get("video")
        if not isinstance(media, dict) or not isinstance(media.get("relative_path"), str):
            return ToolResult(success=False, error="PACKAGE_MEDIA_INVALID: relative_path is required")
        try:
            media_path = _path_within(output_dir, media["relative_path"])
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))
        if not media_path.is_file():
            return ToolResult(success=False, error=f"MEDIA_NOT_FOUND: {media_path}")

        expected_hash = media.get("sha256")
        if not isinstance(expected_hash, str) or _sha256(media_path) != expected_hash:
            return ToolResult(success=False, error="MEDIA_HASH_MISMATCH: staged MP4 was modified")
        try:
            media_info = _probe_media(media_path)
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        metadata_mismatches = _metadata_mismatches(media, media_info)
        if metadata_mismatches:
            return ToolResult(
                success=False,
                error=(
                    "MEDIA_METADATA_MISMATCH: package disagrees with ffprobe for "
                    + ", ".join(metadata_mismatches)
                ),
            )

        privacy = package.get("privacy_review")
        privacy_status = privacy.get("status") if isinstance(privacy, dict) else None
        if privacy_status not in PRIVACY_REVIEW_STATUSES:
            return ToolResult(
                success=False,
                error="PRIVACY_REVIEW_INVALID: package must contain pending, passed, or blocked",
            )
        if privacy_status == "blocked":
            return ToolResult(
                success=False,
                data={
                    "status": "blocked",
                    "ready_for_pipeline": False,
                    "ready_for_publish": False,
                    "privacy_review": "blocked",
                    "package_path": str(package_path),
                    "media_path": str(media_path),
                },
                error="PRIVACY_REVIEW_BLOCKED: package is not approved for pipeline use",
            )

        status = "passed" if privacy_status == "passed" else "pending"
        return ToolResult(
            success=True,
            data={
                "status": status,
                "ready_for_pipeline": True,
                "ready_for_publish": privacy_status == "passed",
                "privacy_review": privacy_status,
                "package_path": str(package_path),
                "media_path": str(media_path),
                "media_relative_path": media["relative_path"],
                "sha256": expected_hash,
                "media": media_info,
                "upstream_commit": UPSTREAM_COMMIT,
            },
            artifacts=[str(media_path), str(package_path)],
        )

    @staticmethod
    def _required_permissions(system: str) -> list[dict[str, str]]:
        if system == "Darwin":
            return [
                {"name": "screen_recording", "status": "unknown", "required": "yes"},
                {"name": "accessibility_cursor_tracking", "status": "unknown", "required": "yes"},
                {"name": "microphone", "status": "unknown", "required": "when enabled"},
                {"name": "camera", "status": "unknown", "required": "when enabled"},
            ]
        if system == "Linux":
            return [
                {"name": "xdg_desktop_portal", "status": "unknown", "required": "on Wayland"},
                {"name": "pipewire_system_audio", "status": "unknown", "required": "for system audio"},
            ]
        if system == "Windows":
            return [
                {"name": "windows_graphics_capture", "status": "unknown", "required": "yes"},
                {"name": "microphone", "status": "unknown", "required": "when enabled"},
                {"name": "camera", "status": "unknown", "required": "when enabled"},
            ]
        return []
