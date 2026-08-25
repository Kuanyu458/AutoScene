"""Deterministic audio timing registry tool for ``openmontage-video``.

The existing music-to-video beat-grid implementation remains the canonical
analysis engine.  This tool promotes it to a registry capability and adds a
small, deterministic marker-snap contract without changing the legacy CLI.
"""

from __future__ import annotations

import importlib.util
import json
import math
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_ANALYZER = _ROOT / ".agents" / "skills" / "music-to-video" / "scripts" / "analyze-beatgrid.py"


def _load_legacy_analyzer():
    if not _LEGACY_ANALYZER.is_file():
        raise FileNotFoundError(f"beat analyzer not found: {_LEGACY_ANALYZER}")
    spec = importlib.util.spec_from_file_location("openmontage_legacy_beatgrid", _LEGACY_ANALYZER)
    if spec is None or spec.loader is None:
        raise ImportError("unable to load the beat-grid analyzer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0:
            out.append(number)
    return out


def _load_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        raise ValueError("audiomap or audiomap_path is required")
    path = Path(str(value))
    if not path.is_file():
        raise FileNotFoundError(f"audiomap not found: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("audiomap must be a JSON object")
    return loaded


def _candidate_times(audiomap: dict[str, Any], snap_to: str) -> list[float]:
    grid = audiomap.get("grid", {}) if isinstance(audiomap.get("grid"), dict) else {}
    if snap_to == "downbeat":
        candidates = grid.get("downbeats_sec") or audiomap.get("downbeats")
    elif snap_to == "onset":
        candidates = [
            item.get("t")
            for item in audiomap.get("events", [])
            if isinstance(item, dict) and item.get("t") is not None
        ]
    else:
        candidates = grid.get("beats_sec") or audiomap.get("beats")
    return sorted(set(round(value, 6) for value in _as_float_list(candidates)))


class AudioTiming(BaseTool):
    name = "audio_timing"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "audio_timing"
    provider = "librosa"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg", "python:librosa", "python:numpy", "python:soundfile"]
    install_instructions = (
        "Install FFmpeg and pinned analysis dependencies: "
        "pip install -r requirements-openmontage-video.txt"
    )
    agent_skills = ["music-to-video"]
    capabilities = ["analyze", "snap_markers", "validate", "beat_grid", "audiomap"]
    best_for = [
        "deterministic beat/onset maps for cuts",
        "semantic marker snapping within a declared tolerance",
        "reproducible local analysis without a paid API",
    ]
    not_good_for = ["creative music selection", "automatic editorial decisions without a scene plan"]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string", "enum": ["analyze", "snap_markers", "validate"]},
            "audio_path": {"type": "string"},
            "audiomap": {"type": "object"},
            "audiomap_path": {"type": "string"},
            "output_path": {"type": "string"},
            "phrase_bars": {"type": "integer", "minimum": 1, "maximum": 16, "default": 4},
            "markers": {"type": "array", "items": {"type": "object"}},
            "snap_tolerance_ms": {"type": "number", "minimum": 0, "maximum": 1000, "default": 250},
            "strict": {"type": "boolean", "default": True},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "audiomap": {"type": "object"},
            "markers": {"type": "array"},
            "max_abs_delta_seconds": {"type": "number"},
            "valid": {"type": "boolean"},
        },
    }
    artifact_schema = {"name": "audiomap", "path": "schemas/artifacts/audiomap.schema.json"}
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=256)
    side_effects = ["writes audiomap or marker JSON when output_path is provided"]
    user_visible_verification = [
        "Check audiomap duration and beat grid against the chosen track",
        "Confirm every non-locked semantic marker is within snap tolerance",
    ]
    idempotency_key_fields = ["operation", "audio_path", "audiomap_path", "markers", "snap_tolerance_ms"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        operation = inputs.get("operation")
        try:
            if operation == "analyze":
                result = self._analyze(inputs)
            elif operation == "snap_markers":
                result = self._snap_markers(inputs)
            elif operation == "validate":
                result = self._validate(inputs)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), duration_seconds=round(time.time() - started, 2))
        result.duration_seconds = round(time.time() - started, 2)
        return result

    def _analyze(self, inputs: dict[str, Any]) -> ToolResult:
        audio_path = Path(str(inputs.get("audio_path", "")))
        if not audio_path.is_file():
            return ToolResult(success=False, error=f"audio not found: {audio_path}")
        analyzer = _load_legacy_analyzer()
        raw = analyzer.analyze(str(audio_path), phrase_bars=int(inputs.get("phrase_bars", 4)))
        # The legacy analyzer uses an integer internal version.  Keep it under
        # analysis and expose the stable artifact contract at the boundary.
        audiomap: dict[str, Any] = {
            "version": "1.0",
            "status": "applied",
            "source_tool": self.name,
            "audio": raw.get("audio", {}),
            "tempo": raw.get("tempo", {}),
            "grid": raw.get("grid", {}),
            "analysis": raw,
            "metadata": {"legacy_version": raw.get("version"), "phrase_bars": raw.get("phraseBars", 4)},
        }
        output = inputs.get("output_path")
        artifacts: list[str] = []
        if output:
            output_path = Path(str(output))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(audiomap, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(output_path))
        return ToolResult(success=True, data={"status": "applied", "audiomap": audiomap}, artifacts=artifacts)

    def _snap_markers(self, inputs: dict[str, Any]) -> ToolResult:
        audiomap = _load_map(inputs.get("audiomap") or inputs.get("audiomap_path"))
        markers = inputs.get("markers")
        if not isinstance(markers, list):
            return ToolResult(success=False, error="markers must be an array")
        tolerance = float(inputs.get("snap_tolerance_ms", 250)) / 1000.0
        snapped: list[dict[str, Any]] = []
        violations: list[str] = []
        max_delta = 0.0
        for index, marker in enumerate(markers):
            if not isinstance(marker, dict):
                return ToolResult(success=False, error=f"markers[{index}] must be an object")
            nominal = marker.get("nominal_seconds", marker.get("time_seconds", marker.get("at_seconds")))
            try:
                nominal_value = float(nominal)
            except (TypeError, ValueError):
                return ToolResult(success=False, error=f"markers[{index}] has no numeric time")
            if nominal_value < 0:
                return ToolResult(success=False, error=f"markers[{index}] time cannot be negative")
            locked = bool(marker.get("semantic_locked", False))
            snap_to = str(marker.get("snap_to", "beat"))
            candidates = _candidate_times(audiomap, snap_to)
            nearest = min(candidates, key=lambda t: abs(t - nominal_value)) if candidates else nominal_value
            delta = 0.0 if locked else nearest - nominal_value
            applied = nominal_value if locked else nearest
            within = locked or abs(delta) <= tolerance
            if not within:
                violations.append(f"markers[{index}] nearest {abs(delta):.3f}s exceeds {tolerance:.3f}s")
                applied = nominal_value
                delta = 0.0
            max_delta = max(max_delta, abs(delta))
            item = dict(marker)
            item.update({
                "nominal_seconds": round(nominal_value, 6),
                "applied_seconds": round(applied, 6),
                "delta_seconds": round(delta, 6),
                "snap_kind": "none" if locked or not within else snap_to,
                "semantic_locked": locked,
            })
            snapped.append(item)
        valid = not violations
        data = {
            "status": "applied" if valid else "failed",
            "markers": snapped,
            "max_abs_delta_seconds": round(max_delta, 6),
            "snap_tolerance_seconds": tolerance,
            "valid": valid,
        }
        output = inputs.get("output_path")
        artifacts: list[str] = []
        if output:
            output_path = Path(str(output))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(output_path))
        if violations and bool(inputs.get("strict", True)):
            return ToolResult(success=False, data={**data, "violations": violations}, artifacts=artifacts, error="; ".join(violations))
        return ToolResult(success=True, data={**data, "violations": violations}, artifacts=artifacts)

    def _validate(self, inputs: dict[str, Any]) -> ToolResult:
        audiomap = _load_map(inputs.get("audiomap") or inputs.get("audiomap_path"))
        if audiomap.get("version") != "1.0":
            return ToolResult(success=False, data={"valid": False}, error="audiomap version must be 1.0")
        if audiomap.get("status") not in {"applied", "not_applicable"}:
            return ToolResult(success=False, data={"valid": False}, error="audiomap status is not publishable")
        markers = inputs.get("markers")
        if markers is None:
            return ToolResult(success=True, data={"valid": True, "status": "pass"})
        result = self._snap_markers({**inputs, "operation": "snap_markers", "strict": True})
        if not result.success:
            return ToolResult(success=False, data={"valid": False, **result.data}, error=result.error)
        return ToolResult(success=True, data={"valid": True, "status": "pass", **result.data})
