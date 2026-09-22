from tools.base_tool import ToolResult

from lib.source_media_review import _probe_video
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


class _Registry:
    def __init__(self):
        self.calls = []

    def get(self, name):
        if name == "audio_probe":
            return self
        if name == "frame_sampler":
            return self
        return None

    def execute(self, inputs):
        self.calls.append(inputs)
        if "strategy" in inputs:
            return ToolResult(success=True, data={"frames": [{"path": "frame-1.jpg"}, {"path": "frame-2.jpg"}]})
        return ToolResult(success=True, data={"duration_seconds": 12.0, "resolution": "1920x1080", "channels": 2})


def test_source_media_review_uses_frame_sampler_contract(tmp_path):
    path = tmp_path / "take.mp4"
    path.write_bytes(b"fixture")
    registry = _Registry()

    result = _probe_video(path, registry)

    frame_call = next(call for call in registry.calls if "strategy" in call)
    assert frame_call["strategy"] == "timestamps"
    assert result["representative_frames"] == ["frame-1.jpg", "frame-2.jpg"]


def test_new_artifacts_are_registered_and_schema_valid():
    assert {"editorial_transcript", "cut_review", "edit_timeline"}.issubset(ARTIFACT_NAMES)
    validate_artifact("editorial_transcript", {
        "version": "1.0",
        "source_fingerprint": "abc",
        "words": [],
        "phrases": [],
    })
    validate_artifact("cut_review", {
        "version": "1.0",
        "boundaries": [],
        "summary": {
            "checked_boundaries": 0,
            "passed_boundaries": 0,
            "error_count": 0,
            "warning_count": 0,
            "coverage_complete": True,
        },
        "status": "pass",
    })
    validate_artifact("edit_timeline", {"version": "1.0", "revision": 0, "segments": []})
