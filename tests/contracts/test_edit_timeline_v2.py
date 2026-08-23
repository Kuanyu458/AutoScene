import pytest

from lib.edit_timeline import (
    TimelineContractError,
    adapt_timeline_for_runtime,
    normalize_edit_decisions,
    validate_timeline_v2,
)
from tools.video.video_compose import VideoCompose


def _timeline():
    return {
        "version": "2.0",
        "fps": 30,
        "total_frames": 30,
        "render_runtime": "remotion",
        "renderer_family": "documentary-montage",
        "composition_mode": "templated",
        "cuts": [{
            "id": "cut-1",
            "source": {"ref": "clip.mp4", "in_frame": 30, "out_frame": 60},
            "timeline": {"start_frame": 0, "end_frame": 30},
            "speed": 1.0,
        }],
        "music_sync": {
            "policy": "beat_cut",
            "grid_reliable": True,
            "anchored_cuts": 0,
            "anchor_coverage": 0,
            "median_error_frames": 0,
            "p95_error_frames": 0,
            "max_error_frames": 0,
        },
    }


def test_runtime_adapters_share_one_authoritative_timeline():
    timeline = _timeline()
    ffmpeg = adapt_timeline_for_runtime(timeline, "ffmpeg")["cuts"][0]
    remotion = adapt_timeline_for_runtime(timeline, "remotion")["cuts"][0]
    hyperframes = adapt_timeline_for_runtime(timeline, "hyperframes")["cuts"][0]

    assert (ffmpeg["in_seconds"], ffmpeg["out_seconds"]) == (1.0, 2.0)
    assert (ffmpeg["timeline_start_seconds"], ffmpeg["timeline_end_seconds"]) == (0.0, 1.0)
    assert (remotion["in_seconds"], remotion["out_seconds"], remotion["source_in_seconds"]) == (0.0, 1.0, 1.0)
    assert hyperframes["in_seconds"] == remotion["in_seconds"]
    assert hyperframes["source_in_seconds"] == remotion["source_in_seconds"]


def test_v1_migration_records_legacy_semantics():
    migrated = normalize_edit_decisions({
        "version": "1.0",
        "render_runtime": "remotion",
        "cuts": [
            {"id": "a", "source": "a.mp4", "in_seconds": 0, "out_seconds": 1, "source_in_seconds": 2},
            {"id": "b", "source": "b.mp4", "in_seconds": 1, "out_seconds": 2},
        ],
    })
    validate_timeline_v2(migrated)
    assert migrated["normalization"]["from_version"] == "1.0"
    assert migrated["cuts"][0]["source"] == {"ref": "a.mp4", "in_frame": 60, "out_frame": 90}


def test_gap_or_overlap_is_rejected():
    timeline = _timeline()
    timeline["cuts"][0]["timeline"]["start_frame"] = 1
    with pytest.raises(TimelineContractError, match="gap"):
        validate_timeline_v2(timeline)


def test_hyperframes_atelier_honors_locked_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(
        VideoCompose, "_hyperframes_available", lambda self: False, raising=True
    )
    result = VideoCompose().execute({
        "operation": "render",
        "edit_decisions": {
            "version": "1.0",
            "cuts": [
                {
                    "id": "cut-1",
                    "source": "asset-1",
                    "in_seconds": 0,
                    "out_seconds": 1,
                }
            ],
            "render_runtime": "hyperframes",
            "composition_mode": "atelier",
            "renderer_family": "animation-first",
        },
        "asset_manifest": {
            "version": "1.0",
            "assets": [{"id": "asset-1", "path": "unread.mp4"}],
        },
        "output_path": str(tmp_path / "out.mp4"),
    })
    assert not result.success
    assert "hyperframes" in result.error.lower()
    assert "not available" in result.error.lower() or "blocker" in result.error.lower()
    assert "remotion entry" not in result.error.lower()
