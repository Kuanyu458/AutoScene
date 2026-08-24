from pathlib import Path

from lib.edit_timeline import validate_timeline_v2
from schemas.artifacts import validate_artifact
from tools.video.beat_cut_planner import BeatCutPlanner


def _timing_map(reliable: bool = True):
    anchors = [
        {"id": f"downbeat-{i}", "type": "downbeat", "time_seconds": i, "frame_30": i * 30, "strength": 0.9}
        for i in range(1, 4)
    ]
    if not reliable:
        anchors = [
            {"id": f"phrase-{i}", "type": "phrase", "time_seconds": i, "frame_30": i * 30, "strength": 0.9}
            for i in range(1, 4)
        ]
    return {
        "tempo": {"grid_reliable": reliable},
        "source": {"sha256": "a" * 64},
        "anchors": anchors,
        "sections": [
            {"id": "section-1", "start_seconds": 0, "end_seconds": 2, "recommended_cut_count": 2},
            {"id": "section-2", "start_seconds": 2, "end_seconds": 4, "recommended_cut_count": 2},
        ],
    }


def _slots():
    return [
        {"id": "source-a", "source": "asset-a", "source_out_frame": 120, "kind": "source"},
        {"id": "three-a", "source": "three-a", "source_out_frame": 120, "kind": "procedural_3d"},
        {"id": "source-b", "source": "asset-b", "source_out_frame": 120, "kind": "source"},
        {"id": "source-c", "source": "asset-c", "source_out_frame": 120, "kind": "source"},
    ]


def test_planner_outputs_gapless_schema_valid_timeline(tmp_path: Path):
    output = tmp_path / "edit.json"
    result = BeatCutPlanner().execute({
        "timing_map": _timing_map(),
        "slots": _slots(),
        "target_frames": 120,
        "policy": {"mode": "adaptive", "fps": 30, "snap_tolerance_frames": 12},
        "output_path": str(output),
    })

    assert result.success, result.error
    timeline = result.data["timeline_plan"]
    validate_timeline_v2(timeline)
    validate_artifact("edit_decisions", timeline)
    assert [cut["timeline"] for cut in timeline["cuts"]] == [
        {"start_frame": 0, "end_frame": 30},
        {"start_frame": 30, "end_frame": 60},
        {"start_frame": 60, "end_frame": 90},
        {"start_frame": 90, "end_frame": 120},
    ]
    assert timeline["music_sync"]["max_error_frames"] <= 1
    assert timeline["planner_metrics"]["gap_frames"] == 0
    assert any(cut["presentation"]["kind"] == "procedural_3d" for cut in timeline["cuts"])


def test_unreliable_grid_forces_phrase_flow():
    result = BeatCutPlanner().execute({
        "timing_map": _timing_map(reliable=False),
        "slots": _slots(),
        "target_frames": 120,
        "policy": {"mode": "beat_cut", "fps": 30},
    })
    assert result.success, result.error
    assert result.data["timeline_plan"]["music_sync"]["policy"] == "phrase_flow"


def test_duplicate_source_is_explicit_coverage_blocker():
    slots = _slots()
    slots[-1]["source"] = "asset-a"
    result = BeatCutPlanner().execute({
        "timing_map": _timing_map(),
        "slots": slots,
        "target_frames": 120,
        "policy": "adaptive",
    })
    assert not result.success
    assert result.data["code"] == "INSUFFICIENT_UNIQUE_COVERAGE"
