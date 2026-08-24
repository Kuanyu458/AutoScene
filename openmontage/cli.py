"""Small public interface for installing and preparing OpenMontage jobs.

Creative orchestration deliberately remains agent-driven. This module owns
only the portable seams a user on a fresh machine needs: environment diagnosis
and immutable input staging for the ``auto-montage-3d`` pipeline.
"""

from __future__ import annotations

import argparse
import importlib.util
from importlib import metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__


REQUIRED_PYTHON = (3, 12)
REQUIRED_NODE = (22, 0)
PYTHON_IMPORTS = {
    "yaml": "PyYAML",
    "pydantic": "pydantic",
    "jsonschema": "jsonschema",
    "dotenv": "python-dotenv",
    "PIL": "Pillow",
    "numpy": "numpy",
    "librosa": "librosa",
    "soundfile": "soundfile",
}
PINNED_DISTRIBUTIONS = {
    "librosa": "1.0.0",
    "soundfile": "0.14.0",
}


def repository_root(start: str | Path | None = None) -> Path:
    """Find the source checkout without relying on a machine-specific path."""
    configured = os.environ.get("OPENMONTAGE_HOME")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(start).expanduser() if start else Path.cwd(),
        Path(__file__).resolve().parents[1],
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        candidate = candidate.resolve()
        for root in (candidate, *candidate.parents):
            if root in seen:
                continue
            seen.add(root)
            if (root / "AGENT_GUIDE.md").is_file() and (root / "pipeline_defs").is_dir():
                return root
    raise RuntimeError(
        "SOURCE_CHECKOUT_NOT_FOUND: run inside the cloned repository or set "
        "OPENMONTAGE_HOME to its absolute path"
    )


def _command_version(command: str, *args: str) -> dict[str, Any]:
    path = shutil.which(command)
    if not path:
        return {"ok": False, "path": None, "version": None, "error": "command not found"}
    try:
        result = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "path": path, "version": None, "error": str(exc)}
    output = (result.stdout or result.stderr).strip().splitlines()
    return {
        "ok": result.returncode == 0,
        "path": path,
        "version": output[0] if output else None,
        "error": None if result.returncode == 0 else f"exit {result.returncode}",
    }


def _major_minor(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    match = re.search(r"(?:^|\s)v?(\d+)\.(\d+)", text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def doctor_report(root: Path | None = None) -> dict[str, Any]:
    """Return a deterministic, secret-free readiness report."""
    try:
        resolved_root = (root or repository_root()).resolve()
        root_error = None
    except RuntimeError as exc:
        resolved_root = Path.cwd().resolve()
        root_error = str(exc)

    python_ok = sys.version_info[:2] >= REQUIRED_PYTHON
    ffmpeg = _command_version("ffmpeg", "-version")
    ffprobe = _command_version("ffprobe", "-version")
    node = _command_version("node", "--version")
    npm = _command_version("npm", "--version")
    node_version = _major_minor(node["version"])
    node["ok"] = bool(node["ok"] and node_version and node_version >= REQUIRED_NODE)
    if node_version and node_version < REQUIRED_NODE:
        node["error"] = f"Node {REQUIRED_NODE[0]}+ required"

    missing_python = [
        distribution
        for import_name, distribution in PYTHON_IMPORTS.items()
        if importlib.util.find_spec(import_name) is None
    ]
    version_mismatches: dict[str, dict[str, str | None]] = {}
    for distribution, expected in PINNED_DISTRIBUTIONS.items():
        try:
            actual = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            actual = None
        if actual != expected:
            version_mismatches[distribution] = {"expected": expected, "actual": actual}
    layout_missing = [
        relative
        for relative in (
            "AGENT_GUIDE.md",
            "pipeline_defs/auto-montage-3d.yaml",
            "pipeline_defs/screen-demo.yaml",
            "remotion-composer/package-lock.json",
            "schemas/artifacts/music_timing_map.schema.json",
            "schemas/artifacts/screen_capture_package.schema.json",
            "tools/capture/recordly_recorder.py",
        )
        if not (resolved_root / relative).exists()
    ]

    try:
        from lib.pipeline_loader import load_pipeline

        pipeline = load_pipeline("auto-montage-3d")
        pipeline_check: dict[str, Any] = {
            "ok": True,
            "name": pipeline.get("name"),
            "stability": pipeline.get("stability"),
        }
    except Exception as exc:
        pipeline_check = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        from tools.graphics.remotion_three_scene import RemotionThreeScene

        result = RemotionThreeScene().execute({"operation": "doctor"})
        three_check: dict[str, Any] = dict(result.data or {})
        three_check["ok"] = bool(result.success and three_check.get("available"))
        if result.error:
            three_check["error"] = result.error
    except Exception as exc:
        three_check = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        from tools.capture.recordly_recorder import RecordlyRecorder

        recordly_tool = RecordlyRecorder()
        result = recordly_tool.execute({"operation": "doctor"})
        recordly_data = dict(result.data or {})
        installed = bool(recordly_data.get("installed"))
        recordly_check: dict[str, Any] = {
            "ok": bool(result.success),
            "optional": True,
            "available": installed,
            "status": recordly_tool.get_status().value,
            "application_version": recordly_data.get("application_version"),
            "platform_supported": bool(recordly_data.get("platform_supported")),
            "ingest_ready": bool(recordly_data.get("ingest_ready")),
            "permissions": recordly_data.get("required_permissions", []),
            "upstream_commit": recordly_data.get("upstream_commit"),
            "message": (
                "Recordly detected; recording remains a visible user-operated step."
                if installed
                else "Recordly not detected (optional); an existing exported MP4 can still be ingested when ffprobe is ready."
            ),
        }
        if result.error:
            recordly_check["error"] = result.error
    except Exception as exc:
        recordly_check = {
            "ok": False,
            "optional": True,
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    checks = {
        "source_checkout": {
            "ok": root_error is None and not layout_missing,
            "root": str(resolved_root),
            "missing": layout_missing,
            "error": root_error,
        },
        "python": {
            "ok": python_ok,
            "version": platform.python_version(),
            "executable": sys.executable,
            "required": ">=3.12",
        },
        "python_dependencies": {
            "ok": not missing_python and not version_mismatches,
            "missing": missing_python,
            "version_mismatches": version_mismatches,
        },
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "node": {**node, "required": ">=22"},
        "npm": npm,
        "auto_montage_pipeline": pipeline_check,
        "remotion_three": three_check,
        "recordly_capture": recordly_check,
    }
    required = tuple(name for name, check in checks.items() if not check.get("optional"))
    blockers = [name for name in required if not checks[name].get("ok")]
    return {
        "schema": "OpenMontageDoctor@1.0",
        "version": __version__,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "ready": not blockers,
        "blockers": blockers,
        "checks": checks,
        "notes": [
            "API keys are optional and are never printed by doctor.",
            "HyperFrames is optional for auto-montage-3d v1; Remotion is the tested renderer.",
            "Remotion has its own license; review THIRD_PARTY_NOTICES.md before commercial use.",
        ],
    }


def _print_doctor(report: dict[str, Any]) -> None:
    print(f"AutoScene {report['version']} — {'READY' if report['ready'] else 'BLOCKED'}")
    for name, check in report["checks"].items():
        marker = "OK" if check.get("ok") else "FAIL"
        detail = check.get("version") or check.get("error") or check.get("message") or ""
        print(f"  [{marker:4}] {name}{': ' + str(detail) if detail else ''}")
    if report["blockers"]:
        print("\nBlockers: " + ", ".join(report["blockers"]))
        print("Run: python scripts/bootstrap.py")


def _doctor_command(args: argparse.Namespace) -> int:
    try:
        root = repository_root(args.root) if args.root else repository_root()
    except RuntimeError:
        root = None
    report = doctor_report(root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        _print_doctor(report)
    return 0 if report["ready"] else 3


def _init_command(args: argparse.Namespace) -> int:
    from lib.montage_request import MontageRequestError, prepare_montage_request

    try:
        root = repository_root(args.root) if args.root else repository_root()
        inputs: dict[str, Any] = {
            "input_dir": args.input_dir,
            "slug": args.slug,
            "brief_path": args.brief,
            "music_path": args.music,
            "target_duration_seconds": args.duration,
            "beat_sync_policy": args.policy,
            "three_d_enabled": not args.no_3d,
            "allow_repeat": args.allow_repeat,
        }
        resolved = prepare_montage_request(
            {key: value for key, value in inputs.items() if value is not None},
            projects_root=args.projects_root or root / "projects",
        )
    except MontageRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    request_path = Path(resolved["output"]["project_dir"]) / "montage_request.json"
    if args.json:
        print(json.dumps(resolved, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Prepared immutable job: {request_path}")
        print("\nNext, open this checkout in a supported AI coding assistant and use:")
        print(
            "  Use the auto-montage-3d pipeline. Read AGENT_GUIDE.md first, "
            f"then continue from {request_path}."
        )
    return 0


def build_parser(*, prog: str = "openmontage") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Portable setup and job preparation for the agent-driven AutoScene "
            "source checkout. The openmontage command remains a compatibility alias."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check local zero-key runtime readiness")
    doctor.add_argument("--root", help="source checkout root (normally auto-detected)")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor.set_defaults(handler=_doctor_command)

    init = subparsers.add_parser("init", help="copy and hash a prepared media folder into a fresh job")
    init.add_argument("input_dir", help="folder containing brief, one music track, and media")
    init.add_argument("--root", help="source checkout root (normally auto-detected)")
    init.add_argument("--projects-root", help="job destination root (default: <checkout>/projects)")
    init.add_argument("--slug", help="explicit kebab-case job slug; collisions fail")
    init.add_argument("--brief", help="explicit brief path")
    init.add_argument("--music", help="explicit music path")
    init.add_argument("--duration", type=float, help="target seconds; default is music-derived")
    init.add_argument("--policy", choices=("adaptive", "beat_cut", "phrase_flow"), default="adaptive")
    init.add_argument("--no-3d", action="store_true", help="explicitly disable procedural 3D")
    init.add_argument("--allow-repeat", action="store_true", help="allow source reuse when coverage is short")
    init.add_argument("--json", action="store_true", help="emit the resolved MontageRequest JSON")
    init.set_defaults(handler=_init_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    executable = Path(sys.argv[0]).stem.lower() if argv is None else "openmontage"
    prog = "autoscene" if executable == "autoscene" else "openmontage"
    parser = build_parser(prog=prog)
    args = parser.parse_args(argv)
    return int(args.handler(args))
