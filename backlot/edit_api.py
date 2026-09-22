"""Backlot edit-timeline routes.

These routes are intentionally an authoring API, not a browser renderer.  The
API stores the shared ``edit_timeline`` artifact inside a project, uses
optimistic revisions for concurrent Agent/UI edits, and leaves final output to
the normal native composition pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import os
import tempfile
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional

from fastapi import File, FastAPI, Form, HTTPException, UploadFile

from lib.edit_timeline import apply_timeline_operations, normalize_edit_decisions
from schemas.artifacts import validate_artifact


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _timeline_path(project_dir: Path) -> Path:
    return project_dir / "artifacts" / "edit_timeline.json"


def _load_timeline(project_dir: Path) -> dict[str, Any]:
    path = _timeline_path(project_dir)
    timeline = _read_json(path)
    if timeline is not None:
        validate_artifact("edit_timeline", timeline)
        return timeline

    decisions = _read_json(project_dir / "artifacts" / "edit_decisions.json")
    if decisions is None:
        raise FileNotFoundError("edit_timeline.json or edit_decisions.json not found")
    return normalize_edit_decisions(decisions)


EDIT_LOCK = Lock()

_ASSET_EXTENSIONS = {
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    ".svg": ("svg", "image/svg+xml"),
    ".glb": ("glb", "model/gltf-binary"),
    ".mp4": ("video", "video/mp4"),
    ".webm": ("video", "video/webm"),
}
_MAX_ASSET_BYTES = 100 * 1024 * 1024
_SAFE_ASSET_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _asset_kind(filename: str) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    try:
        return _ASSET_EXTENSIONS[suffix]
    except KeyError as exc:
        raise ValueError(f"unsupported studio asset type: {suffix or 'unknown'}") from exc


def _validate_asset_bytes(kind: str, content_type: str | None, data: bytes) -> None:
    if kind == "glb" and not data.startswith(b"glTF"):
        raise ValueError("GLB asset is missing the glTF binary header")
    if kind == "svg":
        # SVG is kept as an authored visual layer, so active content and
        # external references are rejected instead of being rendered.
        text = data.decode("utf-8", errors="strict")
        if re.search(r"<\s*script\b|\bon[a-z]+\s*=|(?:href|src)\s*=\s*['\"]https?://", text, re.I):
            raise ValueError("SVG contains executable or external content")


def _store_asset(
    project_dir: Path,
    upload: UploadFile,
    *,
    source: str,
    license_name: str,
) -> dict[str, Any]:
    filename = Path(upload.filename or "").name
    if not filename or filename in {".", ".."}:
        raise ValueError("asset filename is required")
    kind, expected_mime = _asset_kind(filename)
    data = upload.file.read(_MAX_ASSET_BYTES + 1)
    if len(data) > _MAX_ASSET_BYTES:
        raise ValueError(f"asset exceeds {_MAX_ASSET_BYTES // (1024 * 1024)} MiB limit")
    _validate_asset_bytes(kind, upload.content_type, data)
    digest = hashlib.sha256(data).hexdigest()
    safe_name = _SAFE_ASSET_NAME.sub("-", filename).strip(".-") or f"asset{Path(filename).suffix.lower()}"
    relative = Path("assets") / "studio" / f"{digest[:16]}-{safe_name}"
    target = project_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    return {
        "id": f"studio-{digest[:16]}",
        "kind": kind,
        "path": relative.as_posix(),
        "sha256": digest,
        "bytes": len(data),
        "provenance": {
            "source": source or "user-upload",
            "license": license_name or "user-supplied",
        },
        "dimensions": {},
        "qa": {"content_type": upload.content_type or expected_mime, "validated": True},
    }


def _write_timeline(project_dir: Path, timeline: dict[str, Any]) -> Path:
    validate_artifact("edit_timeline", timeline)
    target = _timeline_path(project_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".edit_timeline_", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(timeline, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(temporary).replace(target)
    except Exception:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _apply_timeline_patch(
    project_dir: Path,
    base_revision: int,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    # Keep load, revision check, and replace in one critical section so two
    # Backlot tabs in this process cannot both commit the same base revision.
    with EDIT_LOCK:
        current = _load_timeline(project_dir)
        updated = apply_timeline_operations(
            current,
            operations,
            expected_revision=base_revision,
        )
        _write_timeline(project_dir, updated)
        return updated


def register_edit_routes(
    app: FastAPI,
    project_resolver: Callable[[str], Path],
    *,
    on_changed: Optional[Callable[[str], None]] = None,
) -> None:
    """Register project edit-timeline endpoints on an existing FastAPI app."""

    @app.get("/api/project/{project_id}/edit-timeline")
    async def get_edit_timeline(project_id: str) -> dict[str, Any]:
        project_dir = project_resolver(project_id)
        try:
            return await asyncio.to_thread(_load_timeline, project_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid edit timeline: {exc}") from exc

    @app.patch("/api/project/{project_id}/edit-timeline")
    async def patch_edit_timeline(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project_dir = project_resolver(project_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        if "base_revision" not in payload:
            raise HTTPException(status_code=400, detail="base_revision is required")
        operations = payload.get("operations", [])
        if not isinstance(operations, list):
            raise HTTPException(status_code=400, detail="operations must be an array")

        try:
            updated = await asyncio.to_thread(
                _apply_timeline_patch,
                project_dir,
                int(payload["base_revision"]),
                operations,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            if "revision conflict" in str(exc):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"could not persist edit timeline: {exc}") from exc
        if on_changed is not None:
            on_changed(project_id)
        return updated

    @app.post("/api/project/{project_id}/edit-timeline/validate")
    async def validate_edit_timeline(project_id: str) -> dict[str, Any]:
        project_dir = project_resolver(project_id)
        try:
            timeline = await asyncio.to_thread(_load_timeline, project_dir)
            validate_artifact("edit_timeline", timeline)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid edit timeline: {exc}") from exc
        return {
            "valid": True,
            "revision": int(timeline.get("revision", 0)),
            "visual_layer_count": len(timeline.get("visual_layers", [])),
            "camera_track_count": len(timeline.get("camera_tracks", [])),
            "asset_count": len(timeline.get("asset_manifest", [])),
        }

    @app.post("/api/project/{project_id}/studio-assets")
    async def upload_studio_asset(
        project_id: str,
        file: UploadFile = File(...),
        source: str = Form("user-upload"),
        license_name: str = Form("user-supplied"),
    ) -> dict[str, Any]:
        project_dir = project_resolver(project_id)
        try:
            asset = await asyncio.to_thread(
                _store_asset,
                project_dir,
                file,
                source=source,
                license_name=license_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()
        if on_changed is not None:
            on_changed(project_id)
        return {"asset": asset, "attach_operation": {"op": "attach_asset", "asset": asset}}
