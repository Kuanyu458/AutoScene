"""Safe browser capture tool for the ``openmontage-video`` pipeline.

The tool owns the Node Playwright runner and exposes only a declarative flow
vocabulary.  It accepts Recordly exports as provided media elsewhere in the
pipeline; it does not pretend that Recordly has a headless/CLI contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from tools.base_tool import (
    BaseTool,
    DependencyError,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_DIR = Path(__file__).resolve().parent / "playwright_runtime"
_RUNNER = _RUNTIME_DIR / "runner.mjs"
_ALLOWED_OPS = {
    "goto", "click", "fill", "select", "press", "scroll", "wait",
    "assert", "hold", "screenshot",
}
_ALLOWED_STEP_KEYS = {
    "op", "url", "selector", "value", "text", "seconds", "x", "y",
    "amount", "key", "path", "expected",
}
_SECRET_KEY_WORDS = {
    "password", "passwd", "api_key", "apikey", "token", "cookie",
    "authorization", "secret", "private_key", "storage_state",
}


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"only http(s) URLs are allowed: {url}")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"


def _contains_secret(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else str(key)
            if str(key).lower() in _SECRET_KEY_WORDS:
                return current
            found = _contains_secret(item, current)
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _contains_secret(item, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("sk-", "Bearer ", "ghp_", "github_pat_")):
            return path
    return None


def _safe_screenshot_path(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("screenshot paths must stay inside the capture output")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("screenshot paths must use a supported image extension")


class PlaywrightRecorder(BaseTool):
    name = "playwright_recorder"
    version = "0.1.0"
    tier = ToolTier.SOURCE
    capability = "browser_capture"
    provider = "playwright"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:node", "binary:ffmpeg"]
    install_instructions = (
        "Run npm ci in tools/capture/playwright_runtime, then run "
        "npx playwright install chromium. Node 22 is required."
    )
    agent_skills = ["playwright-recording"]
    capabilities = ["preflight", "dry_run", "record", "recordly_import_contract"]
    best_for = [
        "declarative localhost or allow-listed browser UI capture",
        "Recordly-style cursor, click ripple, focus map, and WebM/MP4 output",
        "reproducible Playwright flows with no arbitrary JavaScript or shell",
    ]
    not_good_for = [
        "native desktop application capture",
        "Recordly .recordly project parsing",
        "flows that need login, cross-origin iframes, or arbitrary code",
    ]
    input_schema = {
        "type": "object",
        "required": ["operation", "base_url"],
        "properties": {
            "operation": {"type": "string", "enum": ["preflight", "dry_run", "record"]},
            "base_url": {"type": "string"},
            "allowed_origins": {"type": "array", "items": {"type": "string"}},
            "flows": {"type": "array", "items": {"type": "object"}},
            "output_path": {"type": "string"},
            "viewport": {
                "type": "object",
                "properties": {"width": {"type": "integer"}, "height": {"type": "integer"}},
            },
            "slow_mo": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 75},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800, "default": 600},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "output_path": {"type": "string"},
            "webm_path": {"type": "string"},
            "manifest_path": {"type": "string"},
            "privacy_report_path": {"type": "string"},
            "contact_sheet_path": {"type": ["string", "null"]},
            "thumbnail_paths": {"type": "array"},
            "sha256": {"type": "string"},
            "focus_map": {"type": "array"},
            "interaction_events": {"type": "array"},
            "screenshot_paths": {"type": "array"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=1200, network_required=True)
    side_effects = ["opens a fresh browser context and writes recording artifacts"]
    user_visible_verification = [
        "Review the privacy report and contact sheet before accepting the recording",
        "Confirm every click/focus event corresponds to the intended UI result",
    ]
    idempotency_key_fields = ["base_url", "allowed_origins", "flows", "output_path", "viewport"]

    def _playwright_package(self) -> str | None:
        """Resolve the pinned package without invoking a shell."""
        candidates = [
            _RUNTIME_DIR / "node_modules" / "playwright",
            _ROOT / "node_modules" / "playwright",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        node = shutil.which("node")
        if not node:
            return None
        try:
            probe = subprocess.run(
                [node, "-e", "process.stdout.write(require.resolve('playwright'))"],
                cwd=str(_RUNTIME_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                return probe.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    def _node_major_version(self) -> int | None:
        node = shutil.which("node")
        if not node:
            return None
        try:
            proc = subprocess.run(
                [node, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=5,
            )
            raw = proc.stdout.strip().lstrip("v")
            return int(raw.split(".", 1)[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _chromium_executable(self) -> str | None:
        node = shutil.which("node")
        if not node or not self._playwright_package():
            return None
        try:
            probe = subprocess.run(
                [node, "--input-type=module", "-e", "import { chromium } from 'playwright'; process.stdout.write(chromium.executablePath())"],
                cwd=str(_RUNTIME_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            )
            path = probe.stdout.strip()
            return path if probe.returncode == 0 and path and Path(path).is_file() else None
        except (OSError, subprocess.SubprocessError):
            return None

    def check_dependencies(self) -> None:
        super().check_dependencies()
        if not _RUNNER.is_file():
            raise DependencyError(f"Playwright runner missing: {_RUNNER}")
        node_major = self._node_major_version()
        if node_major is None or node_major < 22:
            raise DependencyError("Node.js 22 or newer is required for the pinned Playwright runtime")
        if not self._playwright_package():
            raise DependencyError(
                "Playwright package is not installed. Run npm ci in "
                f"{_RUNTIME_DIR} and install Chromium."
            )
        if not self._chromium_executable():
            raise DependencyError("Playwright Chromium is not installed. Run npx playwright install chromium.")

    def _validate_request(self, inputs: dict[str, Any]) -> dict[str, Any]:
        secret_path = _contains_secret(inputs)
        if secret_path:
            raise ValueError(f"credential-like input is blocked: {secret_path}")
        base_url = str(inputs.get("base_url", ""))
        base_origin = _origin(base_url)
        allowed = {_origin(str(item)) for item in inputs.get("allowed_origins", [])}
        host = urlparse(base_origin).hostname or ""
        if host not in {"localhost", "127.0.0.1", "::1"} and base_origin not in allowed:
            raise ValueError("non-local base_url requires an explicit allowed_origins entry")
        flows = inputs.get("flows", [])
        if not isinstance(flows, list) or not flows:
            raise ValueError("at least one declarative flow is required")
        normalized_flows: list[dict[str, Any]] = []
        for flow_index, flow in enumerate(flows):
            if not isinstance(flow, dict) or not flow.get("steps"):
                raise ValueError(f"flow {flow_index} has no steps")
            steps: list[dict[str, Any]] = []
            for step_index, step in enumerate(flow["steps"]):
                if not isinstance(step, dict) or step.get("op") not in _ALLOWED_OPS:
                    raise ValueError(f"flow {flow_index} step {step_index} uses a blocked operation")
                unknown_keys = set(step) - _ALLOWED_STEP_KEYS
                if unknown_keys:
                    raise ValueError(f"flow {flow_index} step {step_index} has blocked fields: {sorted(unknown_keys)}")
                op = step["op"]
                if op in {"click", "fill", "select", "press", "assert", "hold", "screenshot"} and not step.get("selector"):
                    raise ValueError(f"flow {flow_index} step {step_index} needs a selector")
                if op == "fill" and any(word in str(step.get("selector", "")).lower() for word in ("password", "passwd", "token", "api-key", "apikey", "secret", "cookie", "login")):
                    raise ValueError(f"flow {flow_index} step {step_index} targets a credential/login field")
                if op == "screenshot":
                    _safe_screenshot_path(str(step.get("path", "")))
                if op == "goto" and step.get("url"):
                    target = urljoin(base_url, str(step["url"]))
                    if _origin(target) != base_origin and _origin(target) not in allowed:
                        raise ValueError(f"flow {flow_index} step {step_index} leaves the origin allow-list")
                steps.append(dict(step))
            normalized_flows.append({"name": flow.get("name", f"flow-{flow_index + 1}"), "steps": steps})
        viewport = inputs.get("viewport") or {"width": 1920, "height": 1080}
        width, height = int(viewport.get("width", 1920)), int(viewport.get("height", 1080))
        if not (320 <= width <= 7680 and 240 <= height <= 4320):
            raise ValueError("viewport is outside the supported range")
        return {
            **inputs,
            "base_url": base_url,
            "allowed_origins": sorted(allowed),
            "flows": normalized_flows,
            "viewport": {"width": width, "height": height},
            "slow_mo": int(inputs.get("slow_mo", 75)),
        }

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        try:
            request = self._validate_request(inputs)
            operation = request.get("operation")
            if operation in {"preflight", "dry_run"}:
                result = self._preflight(request, dry_run=operation == "dry_run")
            elif operation == "record":
                result = self._record(request)
            else:
                result = ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as exc:
            result = ToolResult(success=False, error=str(exc))
        result.duration_seconds = round(time.time() - started, 2)
        return result

    def _preflight(self, request: dict[str, Any], *, dry_run: bool) -> ToolResult:
        package = self._playwright_package()
        node_major = self._node_major_version()
        chromium_executable = self._chromium_executable()
        disk_free_mb = None
        output_path = request.get("output_path")
        if output_path:
            try:
                disk_free_mb = round(shutil.disk_usage(Path(str(output_path)).resolve().parent).free / (1024 * 1024), 1)
            except OSError:
                disk_free_mb = 0.0
        available = bool(package and _RUNNER.is_file() and (node_major or 0) >= 22 and chromium_executable)
        if disk_free_mb is not None and disk_free_mb < self.resource_profile.disk_mb:
            available = False
        data = {
            "status": "available" if available else "blocked",
            "base_origin": _origin(request["base_url"]),
            "allowed_origins": request.get("allowed_origins", []),
            "flow_count": len(request["flows"]),
            "operations": sorted({step["op"] for flow in request["flows"] for step in flow["steps"]}),
            "viewport": request["viewport"],
            "package": package,
            "node_major": node_major,
            "chromium_executable": chromium_executable,
            "disk_free_mb": disk_free_mb,
            "runner": str(_RUNNER),
            "recordly_import": "MP4/WebM only; .recordly projects are not parsed",
            "would_execute": dry_run,
        }
        if data["status"] == "blocked":
            blockers = []
            if not (package and _RUNNER.is_file() and (node_major or 0) >= 22 and chromium_executable):
                blockers.append("pinned Playwright package, Node 22, runner, or Chromium unavailable")
            if disk_free_mb is not None and disk_free_mb < self.resource_profile.disk_mb:
                blockers.append(f"less than {self.resource_profile.disk_mb} MB free at output path")
            data["blocker"] = "; ".join(blockers)
        return ToolResult(success=True, data=data)

    def _record(self, request: dict[str, Any]) -> ToolResult:
        preflight = self._preflight(request, dry_run=False)
        if preflight.data.get("status") != "available":
            return ToolResult(success=False, data=preflight.data, error=preflight.data.get("blocker"))
        raw_output_path = request.get("output_path")
        if not raw_output_path:
            return ToolResult(success=False, error="output_path is required for record")
        output_path = Path(str(raw_output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path = output_path.resolve()
        temporary_dir = Path(tempfile.mkdtemp(prefix="openmontage-playwright-", dir=str(output_path.parent)))
        manifest_path = output_path.with_suffix(".capture.json")
        privacy_path = output_path.with_suffix(".privacy.json")
        webm_path = temporary_dir / "capture.webm"
        runner_payload = {
            "base_url": request["base_url"],
            "allowed_origins": request.get("allowed_origins", []),
            "flows": request["flows"],
            "viewport": request["viewport"],
            "slow_mo": request.get("slow_mo", 75),
            "recording_dir": str(temporary_dir),
            "manifest_path": str(manifest_path),
        }
        node = shutil.which("node") or "node"
        try:
            proc = subprocess.run(
                [node, str(_RUNNER)], input=json.dumps(runner_payload),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=int(request.get("timeout_seconds", 600)), cwd=str(_RUNTIME_DIR),
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "Playwright runner failed").strip()[-2000:]
                return ToolResult(success=False, error=detail)
            runner_data = json.loads(proc.stdout.strip().splitlines()[-1])
            source_webm = Path(str(runner_data.get("webm_path", "")))
            if not source_webm.is_file():
                source_webm = webm_path
            if not source_webm.is_file():
                return ToolResult(success=False, error="Playwright runner produced no WebM")
            public_webm = output_path.with_suffix(".webm")
            shutil.copy2(source_webm, public_webm)
            if output_path.suffix.lower() == ".webm":
                # The requested output is already the durable WebM artifact.
                public_webm = output_path
            else:
                self.run_command([
                    "ffmpeg", "-y", "-i", str(public_webm), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(output_path),
                ], timeout=int(request.get("timeout_seconds", 600)))
            if not output_path.is_file():
                return ToolResult(success=False, error="recording conversion produced no output")
            sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
            thumbnails = self._make_thumbnails(output_path)
            contact_sheet = self._make_contact_sheet(output_path)
            runner_data["webm_path"] = str(public_webm)
            manifest_path.write_text(json.dumps(runner_data, ensure_ascii=False, indent=2), encoding="utf-8")
            privacy_report = {
                "version": "1.0",
                "status": "awaiting_human",
                "checks": {
                    "rights": "unknown",
                    "privacy": "pass",
                    "origins": "pass",
                    "credentials": "pass",
                },
                "items": [{
                    "path": str(output_path),
                    "sha256": sha256,
                    "source": "playwright",
                    "note": "Human must confirm website/content recording rights before publish.",
                }],
                "blocked_reasons": [],
                "metadata": {"base_origin": _origin(request["base_url"])},
            }
            privacy_path.write_text(json.dumps(privacy_report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not manifest_path.is_file():
                manifest_path.write_text(json.dumps(runner_data, ensure_ascii=False, indent=2), encoding="utf-8")
            data = {
                "status": "recorded",
                "output_path": str(output_path),
                "webm_path": str(public_webm),
                "manifest_path": str(manifest_path),
                "privacy_report_path": str(privacy_path),
                "contact_sheet_path": str(contact_sheet) if contact_sheet else None,
                "thumbnail_paths": [str(path) for path in thumbnails],
                "sha256": sha256,
                "focus_map": runner_data.get("focus_map", []),
                "interaction_events": runner_data.get("interaction_events", []),
                "screenshot_paths": runner_data.get("screenshot_paths", []),
                "recording_method": "playwright_recordly_style",
            }
            artifacts = [str(output_path), str(public_webm), str(manifest_path), str(privacy_path)]
            artifacts.extend(
                str(path) for path in runner_data.get("screenshot_paths", []) if Path(path).is_file()
            )
            artifacts.extend(str(path) for path in thumbnails)
            if contact_sheet:
                artifacts.append(str(contact_sheet))
            return ToolResult(success=True, data=data, artifacts=artifacts)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Playwright recording timed out")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=str(exc))
        finally:
            shutil.rmtree(temporary_dir, ignore_errors=True)

    def _make_contact_sheet(self, video_path: Path) -> Path | None:
        sheet = video_path.with_name(f"{video_path.stem}-contact-sheet.jpg")
        try:
            self.run_command([
                "ffmpeg", "-y", "-i", str(video_path), "-vf",
                "fps=1/5,scale=480:-1,tile=2x2:padding=8:margin=8",
                "-frames:v", "1", str(sheet),
            ], timeout=60)
        except Exception:
            return None
        return sheet if sheet.is_file() else None

    def _make_thumbnails(self, video_path: Path) -> list[Path]:
        thumbnail_dir = video_path.with_name(f"{video_path.stem}-thumbnails")
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.run_command([
                "ffmpeg", "-y", "-i", str(video_path), "-vf", "fps=1/5,scale=480:-1",
                "-q:v", "3", str(thumbnail_dir / "thumb-%03d.jpg"),
            ], timeout=60)
        except Exception:
            return []
        return sorted(thumbnail_dir.glob("thumb-*.jpg"))
