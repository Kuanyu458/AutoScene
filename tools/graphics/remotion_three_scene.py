"""Author, render, and verify deterministic procedural Remotion/Three scenes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

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


TOOL_VERSION = "1.0.0"
TEMPLATES = {"ui-depth-stack", "orbital-reveal", "data-constellation"}
NODE_PACKAGES = {
    "remotion": "4.0.484",
    "@remotion/cli": "4.0.484",
    "@remotion/captions": "4.0.484",
    "@remotion/google-fonts": "4.0.484",
    "@remotion/media": "4.0.484",
    "@remotion/player": "4.0.484",
    "@remotion/three": "4.0.484",
    "@remotion/transitions": "4.0.484",
    "three": "0.155.0",
    "@react-three/fiber": "8.18.0",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_spec(raw: dict[str, Any]) -> dict[str, Any]:
    spec = json.loads(json.dumps(raw))
    required = {"version", "id", "template_id", "duration_frames", "seed"}
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError(f"ThreeSceneSpec missing fields: {missing}")
    if spec["version"] != "1.0":
        raise ValueError("ThreeSceneSpec version must be '1.0'")
    if spec["template_id"] not in TEMPLATES:
        raise ValueError(f"Unknown template_id: {spec['template_id']}")
    spec.setdefault("fps", 30)
    spec.setdefault("width", 1920)
    spec.setdefault("height", 1080)
    if (spec["fps"], spec["width"], spec["height"]) != (30, 1920, 1080):
        raise ValueError("v1 procedural 3D output is fixed at 1920x1080, 30fps")
    if int(spec["duration_frames"]) < 1:
        raise ValueError("duration_frames must be positive")
    spec["duration_frames"] = int(spec["duration_frames"])
    spec["seed"] = int(spec["seed"])
    spec.setdefault("theme", {})
    spec["theme"] = {
        "background": spec["theme"].get("background", "#07111F"),
        "primary": spec["theme"].get("primary", "#4CC9F0"),
        "accent": spec["theme"].get("accent", "#F72585"),
        "foreground": spec["theme"].get("foreground", "#F8FAFC"),
    }
    cues = sorted(set(int(frame) for frame in spec.get("beat_cue_frames", []) if 0 <= int(frame) < spec["duration_frames"]))
    spec["beat_cue_frames"] = cues
    for optional in ("camera", "lighting", "content"):
        if optional in spec and not isinstance(spec[optional], dict):
            raise ValueError(f"{optional} must be an object")
    return spec


class RemotionThreeScene(BaseTool):
    name = "remotion_three_scene"
    version = TOOL_VERSION
    tier = ToolTier.GENERATE
    capability = "graphics"
    provider = "remotion-three"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU
    dependencies = ["cmd:node", "cmd:npx", "cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = (
        "cd remotion-composer && npm ci; requires the Remotion family at 4.0.484, "
        "three@0.155.0, @react-three/fiber@8.18.0"
    )
    agent_skills = ["remotion-best-practices", "threejs-fundamentals", "threejs-animation", "ffmpeg"]
    capabilities = ["procedural_3d", "three_scene_render", "seeded_animation", "three_scene_verify"]
    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string", "enum": ["doctor", "render", "verify"]},
            "scene_spec": {"type": "object"},
            "timing_map": {"type": ["object", "string"]},
            "output_dir": {"type": "string"},
        },
    }
    output_schema = {"artifact": "three_scene_package", "version": "1.0"}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, vram_mb=1024, disk_mb=2048, network_required=False)
    idempotency_key_fields = ["scene_spec", "timing_map"]
    side_effects = ["writes local 3D scene source props, H.264 MP4, previews, and package JSON"]
    best_for = ["full-frame procedural 3D inserts synchronized to music cues"]
    not_good_for = ["GLB generation", "transparent overlays", "remote textures or models"]
    user_visible_verification = ["Inspect preview frames", "Confirm non-black render and cue-frame samples"]

    @staticmethod
    def _composer_dir() -> Path:
        return Path(__file__).resolve().parents[2] / "remotion-composer"

    def _runtime_check(self) -> dict[str, Any]:
        composer = self._composer_dir()
        missing = [command for command in ("node", "npx", "ffmpeg", "ffprobe") if not shutil.which(command)]
        versions: dict[str, str | None] = {}
        for package, expected in NODE_PACKAGES.items():
            package_json = composer / "node_modules" / package / "package.json"
            actual = None
            if package_json.is_file():
                try:
                    actual = str(json.loads(package_json.read_text(encoding="utf-8"))["version"])
                except Exception:
                    actual = None
            versions[package] = actual
            if actual != expected:
                missing.append(f"{package}@{expected}")
        entry = composer / "src" / "ProceduralThree.tsx"
        if not entry.is_file():
            missing.append(str(entry))
        return {
            "available": not missing,
            "missing": missing,
            "packages": versions,
            "composer_dir": str(composer),
            "backend": "angle",
        }

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._runtime_check()["available"] else ToolStatus.UNAVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation")
        started = time.time()
        try:
            if operation == "doctor":
                check = self._runtime_check()
                return ToolResult(success=True, data=check, duration_seconds=round(time.time() - started, 3))
            if operation == "render":
                result = self._render(inputs)
            elif operation == "verify":
                result = self._verify(inputs)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as exc:
            return ToolResult(success=False, error=f"THREE_SCENE_{str(operation).upper()}_FAILED: {type(exc).__name__}: {exc}")
        result.duration_seconds = round(time.time() - started, 3)
        return result

    def _render(self, inputs: dict[str, Any]) -> ToolResult:
        check = self._runtime_check()
        if not check["available"]:
            return ToolResult(
                success=False,
                error=f"THREE_RUNTIME_UNAVAILABLE: missing {check['missing']}",
                data={"code": "THREE_RUNTIME_UNAVAILABLE", "runtime_check": check},
            )
        if not isinstance(inputs.get("scene_spec"), dict):
            return ToolResult(success=False, error="scene_spec is required for render")
        output_dir = Path(inputs.get("output_dir", "")).expanduser().resolve()
        if not output_dir.name:
            return ToolResult(success=False, error="output_dir is required for render")
        if output_dir.exists() and any(output_dir.iterdir()):
            return ToolResult(success=False, error=f"OUTPUT_EXISTS: refusing to overwrite {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        preview_dir = output_dir / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)

        spec = _validate_spec(inputs["scene_spec"])
        spec_path = output_dir / "scene_spec.json"
        props_path = output_dir / "render_props.json"
        render_path = output_dir / "render.mp4"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        props_path.write_text(json.dumps({"sceneSpec": spec}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        composer = self._composer_dir()
        command = [
            shutil.which("npx") or "npx", "remotion", "render", str(composer / "src" / "index.tsx"),
            "ProceduralThree", str(render_path), f"--props={props_path}",
            "--codec=h264", "--crf=18", "--gl=angle", "--concurrency=1",
        ]
        completed = subprocess.run(command, cwd=composer, capture_output=True, text=True, timeout=900)
        if completed.returncode != 0 or not render_path.is_file():
            return ToolResult(
                success=False,
                error=f"THREE_SCENE_RENDER_FAILED: {completed.stderr[-4000:] or completed.stdout[-4000:]}",
                data={"code": "THREE_SCENE_RENDER_FAILED", "command": command},
            )

        sample_frames = sorted(set([
            0,
            max(0, spec["duration_frames"] // 2),
            max(0, spec["duration_frames"] - 1),
            *spec.get("beat_cue_frames", []),
        ]))
        previews = []
        for frame in sample_frames:
            preview_path = preview_dir / f"frame-{frame:06d}.png"
            seconds = frame / spec["fps"]
            extraction = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{seconds:.6f}", "-i", str(render_path), "-frames:v", "1", str(preview_path)],
                capture_output=True,
                text=True,
                timeout=90,
            )
            if extraction.returncode != 0 or not preview_path.is_file():
                return ToolResult(success=False, error=f"PREVIEW_EXTRACTION_FAILED at frame {frame}: {extraction.stderr[-1200:]}")
            with Image.open(preview_path).convert("L") as image:
                mean_luma = float(ImageStat.Stat(image).mean[0])
            previews.append({
                "frame": frame,
                "path": str(preview_path),
                "relative_path": preview_path.relative_to(output_dir).as_posix(),
                "sha256": _sha256(preview_path),
                "mean_luma": round(mean_luma, 3),
            })

        package = {
            "version": "1.0",
            "scene_spec": spec,
            "backend": {"runtime": "remotion-three", "gl": "angle", "pixel_ratio": 1},
            "render": {
                "path": str(render_path),
                "relative_path": render_path.relative_to(output_dir).as_posix(),
                "sha256": _sha256(render_path),
                "codec": "h264",
                "duration_frames": spec["duration_frames"],
                "fps": 30,
                "resolution": "1920x1080",
            },
            "previews": previews,
            "verification": {
                "status": "pass" if all(item["mean_luma"] > 1.0 for item in previews) else "fail",
                "non_black": all(item["mean_luma"] > 1.0 for item in previews),
                "missing_dependencies": [],
                "cue_frames_sampled": spec.get("beat_cue_frames", []),
            },
            "provenance": {
                "tool": self.name,
                "tool_version": self.version,
                "spec_sha256": _json_hash(spec),
                "remote_assets": False,
                "wall_clock_animation": False,
                "source_entry": str(composer / "src" / "ProceduralThree.tsx"),
                "source_entry_relative": "remotion-composer/src/ProceduralThree.tsx",
            },
        }
        from schemas.artifacts import validate_artifact

        validate_artifact("three_scene_package", package)
        package_path = output_dir / "three_scene_package.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if package["verification"]["status"] != "pass":
            return ToolResult(success=False, error="THREE_SCENE_VERIFY_FAILED: sampled black frame", data={"package": package})
        return ToolResult(
            success=True,
            data={"package": package, "output_path": str(render_path), "package_path": str(package_path)},
            artifacts=[str(render_path), str(package_path), *[item["path"] for item in previews]],
            seed=spec["seed"],
        )

    def _verify(self, inputs: dict[str, Any]) -> ToolResult:
        output_dir = Path(inputs.get("output_dir", "")).expanduser().resolve()
        package_path = output_dir / "three_scene_package.json"
        if not package_path.is_file():
            return ToolResult(success=False, error=f"PACKAGE_MISSING: {package_path}")
        package = json.loads(package_path.read_text(encoding="utf-8"))
        from schemas.artifacts import validate_artifact

        validate_artifact("three_scene_package", package)
        render_path = output_dir / package["render"].get("relative_path", "render.mp4")
        if not render_path.is_file():
            render_path = Path(package["render"]["path"])
        failures = []
        if not render_path.is_file() or _sha256(render_path) != package["render"]["sha256"]:
            failures.append("render hash mismatch")
        for preview in package["previews"]:
            path = output_dir / preview.get("relative_path", "")
            if not path.is_file():
                path = Path(preview["path"])
            if not path.is_file() or _sha256(path) != preview["sha256"]:
                failures.append(f"preview hash mismatch: {path}")
            if float(preview["mean_luma"]) <= 1.0:
                failures.append(f"black preview: {path}")
        status = "pass" if not failures else "fail"
        return ToolResult(success=status == "pass", data={"status": status, "failures": failures, "package": package}, error="; ".join(failures) or None)
