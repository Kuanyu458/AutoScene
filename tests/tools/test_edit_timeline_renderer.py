from lib.edit_timeline import apply_timeline_operations, normalize_edit_decisions, timeline_to_edit_decisions
from schemas.artifacts import validate_artifact
from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose


def test_video_compose_accepts_edit_timeline(monkeypatch):
    timeline = normalize_edit_decisions({
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "cuts": [{"id": "cut-1", "source": "take.mp4", "in_seconds": 1, "out_seconds": 3}],
    })
    observed = {}
    tool = VideoCompose()

    def fake_compose(inputs):
        observed["decisions"] = inputs["edit_decisions"]
        return ToolResult(success=True, data={"ok": True})

    monkeypatch.setattr(tool, "_compose", fake_compose)
    result = tool.execute({"operation": "compose", "edit_timeline": timeline})

    assert result.success
    assert observed["decisions"]["cuts"][0]["source"] == "take.mp4"
    assert observed["decisions"]["cuts"][0]["in_seconds"] == 1.0


def test_timeline_roundtrip_preserves_renderer_fields_and_zoom():
    timeline = normalize_edit_decisions({
        "version": "1.0",
        "render_runtime": "remotion",
        "renderer_family": "screen-demo",
        "composition_mode": "templated",
        "cuts": [{"id": "cut-1", "source": "take.mp4", "in_seconds": 0, "out_seconds": 3}],
        "subtitles": {"enabled": True, "style": "word-by-word"},
        "audio": {"music": {"asset_id": "music", "volume": 0.1}},
        "overlays": [],
        "metadata": {"delivery_promise": {"kind": "source_footage"}},
    })
    updated = apply_timeline_operations(
        timeline,
        [{"op": "set_zoom_keyframe", "segment_id": "cut-1", "time_seconds": 0.5, "scale": 1.4, "x": 0.25, "y": 0.4}],
        expected_revision=0,
    )
    decisions = timeline_to_edit_decisions(updated)
    assert decisions["subtitles"]["style"] == "word-by-word"
    assert decisions["audio"]["music"]["asset_id"] == "music"
    assert decisions["zoom_keyframes"][0]["scale"] == 1.4
    validate_artifact("edit_decisions", decisions)


def test_ffmpeg_rejects_unrenderable_zoom_keyframes():
    timeline = normalize_edit_decisions({
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "cuts": [{"id": "cut-1", "source": "take.mp4", "in_seconds": 0, "out_seconds": 1}],
    })
    timeline = apply_timeline_operations(
        timeline,
        [{"op": "set_zoom_keyframe", "segment_id": "cut-1", "time_seconds": 0.2, "scale": 1.2, "x": 0.5, "y": 0.5}],
        expected_revision=0,
    )
    result = VideoCompose().execute({"operation": "compose", "edit_timeline": timeline})
    assert not result.success
    assert "cannot render edit_timeline zoom_keyframes" in result.error


def test_hyperframes_rejects_unrenderable_zoom_keyframes():
    timeline = normalize_edit_decisions({
        "version": "1.0",
        "render_runtime": "hyperframes",
        "cuts": [{"id": "cut-1", "source": "take.mp4", "in_seconds": 0, "out_seconds": 1}],
    })
    timeline = apply_timeline_operations(
        timeline,
        [{"op": "set_zoom_keyframe", "segment_id": "cut-1", "time_seconds": 0.2, "scale": 1.2, "x": 0.5, "y": 0.5}],
        expected_revision=0,
    )
    result = VideoCompose().execute({"operation": "render", "edit_timeline": timeline})
    assert not result.success
    assert "stock HyperFrames adapter" in result.error
