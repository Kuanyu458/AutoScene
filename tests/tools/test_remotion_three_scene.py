import hashlib
import json
from pathlib import Path

from tools.base_tool import ToolStatus
from tools.graphics.remotion_three_scene import RemotionThreeScene


def test_doctor_reports_pinned_local_runtime():
    tool = RemotionThreeScene()
    result = tool.execute({"operation": "doctor"})
    assert result.success
    assert result.data["packages"] == {
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
    assert tool.get_status() == ToolStatus.AVAILABLE
    assert result.data["backend"] == "angle"


def test_three_source_obeys_deterministic_animation_contract():
    source = Path(__file__).resolve().parents[2] / "remotion-composer" / "src" / "ProceduralThree.tsx"
    text = source.read_text(encoding="utf-8")
    assert "useCurrentFrame()" in text
    assert "useFrame(" not in text
    assert "requestAnimationFrame" not in text
    assert "Date.now" not in text
    assert "performance.now" not in text
    assert "http://" not in text and "https://" not in text
    assert "animation:" not in text


def test_render_refuses_to_overwrite_existing_package(tmp_path: Path):
    output = tmp_path / "scene"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    result = RemotionThreeScene().execute({
        "operation": "render",
        "scene_spec": {
            "version": "1.0", "id": "smoke", "template_id": "orbital-reveal",
            "duration_frames": 60, "seed": 1,
        },
        "output_dir": str(output),
    })
    assert not result.success
    assert "OUTPUT_EXISTS" in result.error
    assert (output / "keep.txt").read_text() == "keep"


def test_verify_prefers_relative_paths_after_package_is_moved(tmp_path: Path):
    output = tmp_path / "moved-scene"
    previews = output / "previews"
    previews.mkdir(parents=True)
    render = output / "render.mp4"
    render.write_bytes(b"portable-render")

    preview_records = []
    for frame in (0, 30, 59):
        path = previews / f"frame-{frame:06d}.png"
        path.write_bytes(f"preview-{frame}".encode())
        preview_records.append({
            "frame": frame,
            "path": f"/old-machine/project/previews/{path.name}",
            "relative_path": f"previews/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mean_luma": 42.0,
        })

    package = {
        "version": "1.0",
        "scene_spec": {
            "version": "1.0",
            "id": "portable-scene",
            "template_id": "orbital-reveal",
            "duration_frames": 60,
            "fps": 30,
            "width": 1920,
            "height": 1080,
            "seed": 7,
            "theme": {
                "background": "#000000",
                "primary": "#3366ff",
                "accent": "#ffcc00",
                "foreground": "#ffffff",
            },
        },
        "backend": {"runtime": "remotion-three", "gl": "angle", "pixel_ratio": 1},
        "render": {
            "path": "/old-machine/project/render.mp4",
            "relative_path": "render.mp4",
            "sha256": hashlib.sha256(render.read_bytes()).hexdigest(),
            "codec": "h264",
            "duration_frames": 60,
            "fps": 30,
            "resolution": "1920x1080",
        },
        "previews": preview_records,
        "verification": {
            "status": "pass",
            "non_black": True,
            "missing_dependencies": [],
            "cue_frames_sampled": [],
        },
        "provenance": {
            "tool": "remotion_three_scene",
            "tool_version": "1.0.0",
            "spec_sha256": "0" * 64,
            "remote_assets": False,
            "wall_clock_animation": False,
            "source_entry": "/old-machine/OpenMontage/remotion-composer/src/ProceduralThree.tsx",
            "source_entry_relative": "remotion-composer/src/ProceduralThree.tsx",
        },
    }
    (output / "three_scene_package.json").write_text(
        json.dumps(package), encoding="utf-8"
    )

    result = RemotionThreeScene().execute({"operation": "verify", "output_dir": str(output)})

    assert result.success
    assert result.data["status"] == "pass"
