"""Resolve and stage ``MontageRequest@1.0`` inputs without mutating sources."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from schemas.artifacts import validate_artifact


class MontageRequestError(ValueError):
    """Input discovery or safe-staging failure with a stable error code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "auto-montage"


def _discover_files(root: Path, suffixes: set[str]) -> list[Path]:
    return sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def _allocate_project(projects_root: Path, requested_slug: str | None, base: str) -> tuple[str, Path]:
    projects_root.mkdir(parents=True, exist_ok=True)
    slug = _slugify(requested_slug or base)
    candidate = projects_root / slug
    if requested_slug:
        if candidate.exists():
            raise MontageRequestError("PROJECT_EXISTS", f"Project already exists: {candidate}")
        return slug, candidate
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = projects_root / f"{slug}-{suffix}"
    return candidate.name, candidate


def _stage_file(
    source: Path,
    destination: Path,
    media_type: str,
    *,
    project_dir: Path,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_hash = _sha256(source)
    staged_hash = _sha256(destination)
    if source_hash != staged_hash:
        raise MontageRequestError("STAGE_HASH_MISMATCH", f"Copy verification failed: {source}")
    return {
        "source_path": str(source),
        "staged_path": str(destination.resolve()),
        "staged_relative_path": destination.resolve().relative_to(project_dir.resolve()).as_posix(),
        "sha256": source_hash,
        "size_bytes": source.stat().st_size,
        "media_type": media_type,
    }


def prepare_montage_request(
    inputs: dict[str, Any],
    *,
    projects_root: str | Path = "projects",
) -> dict[str, Any]:
    """Discover, hash, and safely stage a montage request into a fresh project.

    Discovery priority is explicit path, conventional filename, then a single
    matching file.  The input directory is read-only; every staged byte is
    hash-verified before the resolved request is returned.
    """
    input_dir = Path(inputs.get("input_dir", "")).expanduser().resolve()
    if not input_dir.is_dir():
        raise MontageRequestError("INPUT_DIR_NOT_FOUND", str(input_dir))

    explicit_brief = inputs.get("brief_path")
    brief = Path(explicit_brief).expanduser().resolve() if explicit_brief else None
    if brief is None:
        brief = next((input_dir / name for name in ("brief.md", "brief.txt") if (input_dir / name).is_file()), None)
    if brief is None or not brief.is_file():
        raise MontageRequestError("BRIEF_MISSING", "Expected brief.md, brief.txt, or brief_path")

    explicit_music = inputs.get("music_path")
    music = Path(explicit_music).expanduser().resolve() if explicit_music else None
    if music is None:
        conventional = [
            path for stem in ("music", "bgm")
            for path in input_dir.glob(f"{stem}.*")
            if path.suffix.lower() in _AUDIO_EXTENSIONS
        ]
        candidates = sorted(set(path.resolve() for path in conventional))
        if not candidates:
            candidates = _discover_files(input_dir, _AUDIO_EXTENSIONS)
        if len(candidates) > 1:
            raise MontageRequestError("MUSIC_AMBIGUOUS", ", ".join(str(p) for p in candidates))
        music = candidates[0] if candidates else None
    if music is None or not music.is_file():
        raise MontageRequestError("MUSIC_MISSING", "No music file found")

    media = [
        path for path in _discover_files(input_dir, _VIDEO_EXTENSIONS | _IMAGE_EXTENSIONS)
        if path != music and path != brief
    ]
    if not media:
        raise MontageRequestError("NO_MEDIA", "At least one video or image is required")

    projects_path = Path(projects_root).expanduser().resolve()
    slug, project_dir = _allocate_project(projects_path, inputs.get("slug"), input_dir.name)
    project_dir.mkdir(parents=True, exist_ok=False)
    for relative in ("artifacts", "inputs/media", "assets/procedural-3d", "renders", "logs"):
        (project_dir / relative).mkdir(parents=True, exist_ok=True)

    brief_record = _stage_file(
        brief, project_dir / "inputs" / brief.name, "brief", project_dir=project_dir
    )
    music_record = _stage_file(
        music, project_dir / "inputs" / music.name, "music", project_dir=project_dir
    )
    media_records = [
        _stage_file(
            path,
            project_dir / "inputs" / "media" / f"{index:03d}-{path.name}",
            "video" if path.suffix.lower() in _VIDEO_EXTENSIONS else "image",
            project_dir=project_dir,
        )
        for index, path in enumerate(media, 1)
    ]

    inventory_material = "\n".join(
        [brief_record["sha256"], music_record["sha256"]]
        + [record["sha256"] for record in media_records]
        + [brief.read_text(encoding="utf-8", errors="replace")]
    )
    resolved = {
        "version": "1.0",
        "project_slug": slug,
        "input_dir": str(input_dir),
        "brief": brief_record,
        "music": music_record,
        "media": media_records,
        "output": {"project_dir": str(project_dir), "request_relative_path": "montage_request.json"},
        "settings": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "beat_sync_policy": inputs.get("beat_sync_policy", "adaptive"),
            "three_d_enabled": bool(inputs.get("three_d_enabled", True)),
            "allow_repeat": bool(inputs.get("allow_repeat", False)),
            "target_duration_seconds": inputs.get("target_duration_seconds"),
            "music_offset_seconds": float(inputs.get("music_offset_seconds", 0)),
        },
        "inventory_sha256": hashlib.sha256(inventory_material.encode("utf-8")).hexdigest(),
        "metadata": {"source_mutation_policy": "read_only", "staging": "copy_and_hash"},
    }
    validate_artifact("montage_request", resolved)
    request_path = project_dir / "montage_request.json"
    request_path.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved
