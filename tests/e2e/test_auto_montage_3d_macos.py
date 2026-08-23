"""Opt-in macOS E2E for the auto-montage-3d beta pipeline.

Run with: OPENMONTAGE_MACOS_E2E=1 pytest -q tests/e2e/test_auto_montage_3d_macos.py
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.artifacts import validate_artifact
from tools.analysis.music_sync_analyzer import MusicSyncAnalyzer
from tools.graphics.remotion_three_scene import RemotionThreeScene
from tools.video.beat_cut_planner import BeatCutPlanner
from tools.video.video_compose import VideoCompose


pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_MACOS_E2E") != "1" or platform.system() != "Darwin",
    reason="Set OPENMONTAGE_MACOS_E2E=1 on macOS to run the real Chromium/WebGL E2E",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
    assert completed.returncode == 0, completed.stderr[-4000:]


def _click_track(path: Path, duration: float = 4.0) -> None:
    sr = 22050
    signal = np.zeros(int(sr * duration), dtype=np.float32)
    for seconds in np.arange(0, duration, 0.5):
        start = int(seconds * sr)
        length = min(int(0.025 * sr), len(signal) - start)
        signal[start:start + length] += (0.9 * np.exp(-np.arange(length) / (0.004 * sr))).astype(np.float32)
    sf.write(path, signal, sr)


def _probe(path: Path) -> dict:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(completed.stdout)


def test_synthetic_sources_music_three_and_final_remotion_render(tmp_path: Path):
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    clips = []
    for index, hue in enumerate((0, 80, 170), 1):
        clip = inputs_dir / f"clip-{index}.mp4"
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
            "-vf", f"hue=h={hue}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(clip),
        ])
        clips.append(clip)
    music = inputs_dir / "music-120bpm.wav"
    _click_track(music)
    source_hashes = {path: _sha(path) for path in [*clips, music]}

    timing_result = MusicSyncAnalyzer().execute({
        "input_path": str(music),
        "output_path": str(tmp_path / "music_timing_map.json"),
    })
    assert timing_result.success, timing_result.error
    timing_map = timing_result.data["timing_map"]
    assert timing_map["tempo"]["grid_reliable"] is True

    three_dir = tmp_path / "procedural-3d" / "three-1"
    three_result = RemotionThreeScene().execute({
        "operation": "render",
        "scene_spec": {
            "version": "1.0",
            "id": "three-1",
            "template_id": "data-constellation",
            "duration_frames": 60,
            "fps": 30,
            "width": 1920,
            "height": 1080,
            "seed": 20260820,
            "beat_cue_frames": [15, 30, 45],
            "content": {"title": "Procedural signal", "subtitle": "Beat-aligned insert"},
        },
        "output_dir": str(three_dir),
    })
    assert three_result.success, three_result.error
    three_video = Path(three_result.data["output_path"])

    slots = [
        {"id": "cut-source-1", "source": "asset-1", "source_out_frame": 60, "kind": "source"},
        {"id": "cut-three-1", "source": "three-1", "source_out_frame": 60, "kind": "procedural_3d"},
        {"id": "cut-source-2", "source": "asset-2", "source_out_frame": 60, "kind": "source"},
        {"id": "cut-source-3", "source": "asset-3", "source_out_frame": 60, "kind": "source"},
    ]
    plan_result = BeatCutPlanner().execute({
        "timing_map": timing_map,
        "slots": slots,
        "target_frames": 120,
        "policy": {"mode": "adaptive", "fps": 30, "snap_tolerance_frames": 3},
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })
    assert plan_result.success, plan_result.error
    timeline = plan_result.data["timeline_plan"]
    timeline["audio"] = {
        "music": {
            "src": str(music),
            "volume": 0.5,
            "offsetSeconds": 0,
            "fadeInSeconds": 0,
            "fadeOutSeconds": 0,
            "loop": False,
        }
    }
    validate_artifact("edit_decisions", timeline)

    assets = {
        "version": "1.0",
        "assets": [
            *[
                {"id": f"asset-{index}", "type": "video", "path": str(clip), "source_tool": "fixture", "scene_id": f"source-{index}"}
                for index, clip in enumerate(clips, 1)
            ],
            {
                "id": "three-1",
                "type": "animation",
                "subtype": "procedural_3d",
                "path": str(three_video),
                "source_tool": "remotion_three_scene",
                "scene_id": "three-1",
                "package_path": three_result.data["package_path"],
                "sha256": _sha(three_video),
                "backend": "remotion-three-angle",
                "cue_frames": [15, 30, 45],
                "provenance": {
                    key: three_result.data["package"]["provenance"][key]
                    for key in (
                        "tool",
                        "tool_version",
                        "spec_sha256",
                        "remote_assets",
                        "wall_clock_animation",
                    )
                },
            },
        ],
    }
    validate_artifact("asset_manifest", assets)

    final = tmp_path / "renders" / "final.mp4"
    render_result = VideoCompose().execute({
        "operation": "render",
        "edit_decisions": timeline,
        "asset_manifest": assets,
        "output_path": str(final),
    })
    assert render_result.success, render_result.error
    assert final.is_file()

    probe = _probe(final)
    video_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert (video_stream["width"], video_stream["height"]) == (1920, 1080)
    assert video_stream["codec_name"] == "h264"
    assert video_stream["avg_frame_rate"] == "30/1"
    assert audio_stream["codec_name"] == "aac"
    assert abs(float(probe["format"]["duration"]) - 4.0) <= 1 / 30
    assert abs(float(video_stream.get("start_time", 0)) - float(audio_stream.get("start_time", 0))) * 1000 <= 100

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(final), "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        timeout=120,
        check=True,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(float)
    changes = np.linalg.norm(np.diff(frames, axis=0), axis=1)
    errors = []
    for boundary in (30, 60, 90):
        window = changes[boundary - 3:boundary + 2]
        detected = boundary - 2 + int(np.argmax(window))
        errors.append(abs(detected - boundary))
    assert max(errors) <= 2
    assert float(np.percentile(errors, 95)) <= 2
    assert timeline["music_sync"]["median_error_frames"] <= 1
    assert all(_sha(path) == digest for path, digest in source_hashes.items())
    assert three_result.data["package"]["verification"]["non_black"] is True
