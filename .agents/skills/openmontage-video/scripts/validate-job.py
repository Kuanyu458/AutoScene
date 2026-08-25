#!/usr/bin/env python3
"""Deterministic validation for an ``openmontage-video`` job.

This helper deliberately does not start a browser, call FFmpeg, or mutate a
project.  It only normalizes defaults and checks the job contract, origin
allow-list, safe flow vocabulary, and feature/approval invariants.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = ROOT / "schemas" / "jobs" / "openmontage_video.schema.json"
ALLOWED_OPS = {
    "goto", "click", "fill", "select", "press", "scroll", "wait",
    "assert", "hold", "screenshot",
}
SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|api[_-]?key|secret|token|cookie|authorization|bearer|"
    r"storage[_-]?state|private[_-]?key|credential)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(r"(?:^sk-[A-Za-z0-9_-]{12,}|^Bearer\s+|^gh[pousr]_[A-Za-z0-9_]{12,})")
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class JobValidationError(ValueError):
    """Raised when a job is structurally or operationally unsafe."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise JobValidationError(f"job file not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise JobValidationError(f"invalid YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise JobValidationError("job must be a YAML mapping")
    return value


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply only documented defaults; never invent a URL or media path."""
    job = json.loads(json.dumps(raw))
    job.setdefault("version", "1.0")
    source = job.setdefault("source", {})
    source.setdefault("media", [])
    recording = job.setdefault("recording", {})
    recording.setdefault("allowed_origins", [])
    recording.setdefault("flows", [])
    features = job.setdefault("features", {})
    for key in ("beat_sync", "ui_3d", "ui_capture"):
        features.setdefault(key, "required")
    edit = job.setdefault("edit", {})
    edit.setdefault("snap_tolerance_ms", 250)
    edit.setdefault("focus_budget_per_scene", 1)
    edit.setdefault("focus_scale", [1.20, 1.35])
    job.setdefault("approvals", {"mode": "guided"})
    output = job.setdefault("output", {})
    output.setdefault("resolution", "1920x1080")
    output.setdefault("fps", 30)
    output.setdefault("language", "zh-TW")
    job.setdefault("decisions", [])
    return job


def _walk_values(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else str(key)
            yield current, key, item
            yield from _walk_values(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_values(item, f"{path}[{index}]")


def _reject_secrets(job: dict[str, Any]) -> None:
    for path, key, value in _walk_values(job):
        if SECRET_KEY_RE.search(str(key)):
            raise JobValidationError(f"credential-like field is not allowed in job.yaml: {path}")
        if isinstance(value, str) and SECRET_VALUE_RE.search(value.strip()):
            raise JobValidationError(f"credential-like value is not allowed in job.yaml: {path}")


def _origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise JobValidationError(f"origin must be an http(s) URL: {value!r}")
    if parsed.username or parsed.password:
        raise JobValidationError("URLs with embedded credentials are not allowed")
    port = f":{parsed.port}" if parsed.port else ""
    host = parsed.hostname.lower()
    return f"{parsed.scheme.lower()}://{host}{port}"


def _validate_origins(recording: dict[str, Any]) -> str:
    base_url = str(recording.get("base_url", ""))
    if not base_url:
        raise JobValidationError("recording.base_url is required")
    base_origin = _origin(base_url)
    allowed = {_origin(str(item)) for item in recording.get("allowed_origins", [])}
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    base_host = urlparse(base_origin).hostname or ""
    if base_host not in local_hosts and base_origin not in allowed:
        raise JobValidationError(
            "non-local recording.base_url requires an explicit matching allowed_origins entry"
        )
    for item in allowed:
        if urlparse(item).hostname not in local_hosts and item not in allowed:
            raise JobValidationError("invalid recording origin allow-list")
    return base_origin


def _safe_path(value: str, *, label: str, allow_absolute: bool = True) -> None:
    if not value or "\x00" in value:
        raise JobValidationError(f"{label} must be a non-empty safe path")
    path = Path(value)
    if not allow_absolute and path.is_absolute():
        raise JobValidationError(f"{label} must be relative")
    if any(part == ".." for part in path.parts):
        raise JobValidationError(f"{label} cannot traverse parent directories")


def _validate_flows(recording: dict[str, Any], base_origin: str) -> None:
    for flow_index, flow in enumerate(recording.get("flows", [])):
        steps = flow.get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise JobValidationError(f"recording.flows[{flow_index}].steps must not be empty")
        for step_index, step in enumerate(steps):
            op = step.get("op")
            prefix = f"recording.flows[{flow_index}].steps[{step_index}]"
            if op not in ALLOWED_OPS:
                raise JobValidationError(f"{prefix}.op is not an allowed browser operation")
            if op in {"click", "fill", "select", "press", "assert", "hold", "screenshot"} and not step.get("selector"):
                raise JobValidationError(f"{prefix}.selector is required for {op}")
            if op == "fill" and not isinstance(step.get("value", step.get("text")), str):
                raise JobValidationError(f"{prefix} fill requires a text value")
            if op == "select" and not isinstance(step.get("value"), str):
                raise JobValidationError(f"{prefix} select requires a string value")
            if op in {"wait", "hold"} and float(step.get("seconds", 0)) < 0:
                raise JobValidationError(f"{prefix}.seconds cannot be negative")
            if op == "screenshot":
                path = step.get("path")
                if not path:
                    raise JobValidationError(f"{prefix}.path is required for screenshot")
                _safe_path(str(path), label=f"{prefix}.path", allow_absolute=False)
                if Path(path).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise JobValidationError(f"{prefix}.path must be an image path")
            if op == "goto" and step.get("url"):
                absolute = urljoin(str(recording["base_url"]), str(step["url"]))
                if _origin(absolute) != base_origin:
                    raise JobValidationError(f"{prefix}.url leaves the allowed recording origin")


def _validate_mode(job: dict[str, Any]) -> None:
    mode = job["source"]["mode"]
    media = job["source"].get("media", [])
    flows = job["recording"].get("flows", [])
    if mode == "provided" and not media:
        raise JobValidationError("provided mode requires source.media")
    if mode == "record" and not flows:
        raise JobValidationError("record mode requires recording.flows")
    if mode == "mixed" and not media and not flows:
        raise JobValidationError("mixed mode requires source.media or recording.flows")
    for index, media_item in enumerate(media):
        media_path = str(media_item.get("path", ""))
        _safe_path(media_path, label=f"source.media[{index}].path")
        suffix = Path(media_path).suffix.lower()
        if suffix == ".recordly":
            raise JobValidationError("Recordly .recordly projects are not parsed; export MP4 or WebM")
        if media_item.get("media_type") == "recordly_export" and suffix not in {".mp4", ".webm"}:
            raise JobValidationError("recordly_export media must be an MP4 or WebM file")


def _validate_features_and_approval(job: dict[str, Any]) -> None:
    decisions = job.get("decisions") or job.get("decision_log") or []
    for feature, value in job["features"].items():
        if value != "off":
            continue
        matched = any(
            feature in str(item.get("subject", "")).lower()
            or feature in str(item.get("decision", "")).lower()
            for item in decisions
            if isinstance(item, dict)
        )
        if not matched:
            raise JobValidationError(
                f"features.{feature}=off requires a matching append-only decision entry"
            )
    if job["approvals"]["mode"] == "autonomous":
        authorized = bool((job.get("metadata") or {}).get("autonomous_authorization"))
        if not authorized:
            raise JobValidationError(
                "autonomous approval mode requires metadata.autonomous_authorization=true"
            )


def validate_job(job: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize(job)
    _reject_secrets(normalized)
    try:
        with SCHEMA_PATH.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        jsonschema.validate(normalized, schema)
    except jsonschema.ValidationError as exc:
        raise JobValidationError(f"job schema validation failed: {exc.message}") from exc
    except json.JSONDecodeError as exc:
        raise JobValidationError(f"job schema is invalid: {exc}") from exc

    if not PROJECT_ID_RE.fullmatch(normalized["project_id"]):
        raise JobValidationError("project_id must be lowercase kebab-case")
    base_origin = _validate_origins(normalized["recording"])
    _validate_flows(normalized["recording"], base_origin)
    _validate_mode(normalized)
    _validate_features_and_approval(normalized)
    if normalized["edit"]["snap_tolerance_ms"] > 250:
        raise JobValidationError("edit.snap_tolerance_ms cannot exceed the 250ms contract")
    if normalized["edit"]["focus_budget_per_scene"] > 1:
        raise JobValidationError("edit.focus_budget_per_scene cannot exceed one focus event per scene")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path, help="Path to job.yaml")
    parser.add_argument("--normalized", action="store_true", help="Print normalized JSON")
    args = parser.parse_args(argv)
    try:
        normalized = validate_job(_load_yaml(args.job))
    except JobValidationError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    result = {"valid": True, "project_id": normalized["project_id"], "mode": normalized["source"]["mode"]}
    if args.normalized:
        result["job"] = normalized
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
