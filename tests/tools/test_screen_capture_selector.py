from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.base_tool import ToolResult, ToolStatus
from tools.capture.cap_recorder import CapRecorder
from tools.capture.screen_capture_selector import ScreenCaptureSelector
from tools.capture.screen_recorder import ScreenRecorder


@dataclass
class FakeProvider:
    provider: str
    name: str
    status: ToolStatus = ToolStatus.AVAILABLE
    installed: bool = True
    running: bool = True
    recording_ready: bool = True
    ingest_ready: bool = True
    recordings: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    install_instructions: str = "install the provider"

    def get_status(self) -> ToolStatus:
        return self.status

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(inputs))
        operation = inputs.get("operation")
        if self.provider == "ffmpeg":
            return ToolResult(
                success=True,
                data={"output_path": inputs["output_path"], "capture_method": "ffmpeg"},
                artifacts=[inputs["output_path"]],
            )
        if operation == "detect":
            return ToolResult(
                success=True,
                data={"installed": self.installed, "running": self.running},
            )
        if operation == "doctor":
            return ToolResult(
                success=True,
                data={
                    "installed": self.installed,
                    "platform_supported": True,
                    "recording_ready": self.recording_ready,
                    "capture_state": "ready" if self.recording_ready else "setup_required",
                    "ingest_ready": self.ingest_ready,
                },
            )
        if operation == "setup_guide":
            return ToolResult(success=True, data={"next_step": "install or open the GUI"})
        if operation == "launch":
            return ToolResult(
                success=True,
                data={"capture_state": "awaiting_human", "launcher_pid": 123},
            )
        if operation == "ingest":
            return ToolResult(
                success=True,
                data={
                    "package_path": f"{inputs['output_dir']}/screen_capture_package.json",
                    "media_path": f"{inputs['output_dir']}/media/recordly-capture.mp4",
                    "privacy_review": inputs.get("privacy_review", "pending"),
                    "ready_for_pipeline": False,
                },
            )
        if operation == "find_recordings":
            return ToolResult(success=True, data={"recordings": list(self.recordings)})
        if operation == "pick_latest":
            return ToolResult(success=False, error="no completed recording")
        raise AssertionError(f"Unexpected fake-provider operation: {operation!r}")


def _selector_with(monkeypatch, *providers: FakeProvider) -> ScreenCaptureSelector:
    selector = ScreenCaptureSelector()
    provider_map = {provider.provider: provider for provider in providers}
    monkeypatch.setattr(selector, "_providers", lambda: provider_map)
    return selector


def _all_ready(monkeypatch):
    ffmpeg = FakeProvider("ffmpeg", "screen_recorder")
    cap = FakeProvider("cap", "cap_recorder")
    recordly = FakeProvider("recordly", "recordly_recorder")
    return _selector_with(monkeypatch, ffmpeg, cap, recordly), ffmpeg, cap, recordly


def test_selector_contract_exposes_recordly_prepare_ingest_and_intent():
    properties = ScreenCaptureSelector.input_schema["properties"]
    assert set(properties["preferred_provider"]["enum"]) == {
        "auto",
        "ffmpeg",
        "cap",
        "recordly",
    }
    assert {"prepare", "ingest"}.issubset(properties["operation"]["enum"])
    assert properties["capture_intent"]["default"] == "automated"
    assert properties["privacy_review"]["enum"] == ["pending", "passed", "blocked"]


def test_fallbacks_are_registered_tool_names_not_provider_ids(monkeypatch):
    selector, *_ = _all_ready(monkeypatch)
    assert selector.fallback_tools == [
        "screen_recorder",
        "cap_recorder",
        "recordly_recorder",
    ]


def test_auto_default_remains_ffmpeg(monkeypatch):
    selector, *_ = _all_ready(monkeypatch)
    result = selector.execute({"operation": "recommend"})
    assert result.success
    assert result.data["recommended_provider"] == "ffmpeg"


def test_polished_product_demo_prefers_live_recordly(monkeypatch):
    selector, *_ = _all_ready(monkeypatch)
    result = selector.execute(
        {"operation": "recommend", "capture_intent": "polished_product_demo"}
    )
    assert result.success
    assert result.data["recommended_provider"] == "recordly"


def test_explicit_unavailable_provider_never_falls_back(monkeypatch):
    ffmpeg = FakeProvider("ffmpeg", "screen_recorder", status=ToolStatus.UNAVAILABLE)
    cap = FakeProvider("cap", "cap_recorder")
    recordly = FakeProvider("recordly", "recordly_recorder")
    selector = _selector_with(monkeypatch, ffmpeg, cap, recordly)

    result = selector.execute(
        {
            "operation": "record",
            "preferred_provider": "ffmpeg",
            "output_path": "capture.mp4",
        }
    )

    assert not result.success
    assert result.data["selected_provider"] == "ffmpeg"
    assert result.data["state"] == "blocked"
    assert cap.calls == []
    assert recordly.calls == []


def test_recordly_prepare_launches_gui_but_stays_awaiting_human(monkeypatch):
    recordly = FakeProvider("recordly", "recordly_recorder")
    selector = _selector_with(monkeypatch, recordly)

    result = selector.execute(
        {"operation": "prepare", "preferred_provider": "recordly"}
    )

    assert result.success
    assert result.data["state"] == "awaiting_human"
    assert result.data["status"] == "awaiting_human"
    assert result.data["requires_human_action"] is True
    assert result.data["selected_provider"] == "recordly"
    assert any(call["operation"] == "launch" for call in recordly.calls)


def test_recordly_record_is_prepare_not_completed_capture(monkeypatch):
    recordly = FakeProvider("recordly", "recordly_recorder")
    selector = _selector_with(monkeypatch, recordly)

    result = selector.execute(
        {"operation": "record", "preferred_provider": "recordly"}
    )

    assert result.success
    assert result.data["capture_state"] == "awaiting_human"
    assert result.data["state"] == "awaiting_human"
    assert "output_path" not in result.data


def test_recordly_prepare_returns_setup_gate_when_app_is_missing(monkeypatch):
    recordly = FakeProvider(
        "recordly",
        "recordly_recorder",
        status=ToolStatus.DEGRADED,
        installed=False,
        recording_ready=False,
    )
    selector = _selector_with(monkeypatch, recordly)

    result = selector.execute(
        {"operation": "prepare", "preferred_provider": "recordly"}
    )

    assert result.success
    assert result.data["state"] == "awaiting_human"
    assert result.data["capture_state"] == "setup_required"
    assert any(call["operation"] == "setup_guide" for call in recordly.calls)
    assert not any(call["operation"] == "launch" for call in recordly.calls)


def test_cap_record_returns_manual_gate_without_picking_latest(monkeypatch):
    cap = FakeProvider("cap", "cap_recorder")
    selector = _selector_with(monkeypatch, cap)

    result = selector.execute({"operation": "record", "preferred_provider": "cap"})

    assert result.success
    assert result.data["state"] == "awaiting_human"
    assert result.data["capture_state"] == "ready_for_human_recording"
    assert [call["operation"] for call in cap.calls] == ["setup_guide"]


def test_explicit_recordly_ingest_works_when_gui_is_not_installed(monkeypatch):
    recordly = FakeProvider(
        "recordly",
        "recordly_recorder",
        status=ToolStatus.DEGRADED,
        installed=False,
        recording_ready=False,
        ingest_ready=True,
    )
    selector = _selector_with(monkeypatch, recordly)

    result = selector.execute(
        {
            "operation": "ingest",
            "preferred_provider": "recordly",
            "input_path": "/explicit/export.mp4",
            "output_dir": "/project/capture-package",
            "privacy_review": "pending",
        }
    )

    assert result.success
    assert result.data["state"] == "ingested"
    assert result.data["selected_provider"] == "recordly"
    ingest_call = next(call for call in recordly.calls if call["operation"] == "ingest")
    assert ingest_call["input_path"] == "/explicit/export.mp4"
    assert ingest_call["output_dir"] == "/project/capture-package"


def test_pick_latest_never_queries_recordly(monkeypatch):
    cap = FakeProvider(
        "cap",
        "cap_recorder",
        recordings=[{"path": "/cap/latest.mp4", "size_mb": 2.5}],
    )
    recordly = FakeProvider("recordly", "recordly_recorder")
    selector = _selector_with(monkeypatch, cap, recordly)

    result = selector.execute({"operation": "pick_latest"})

    assert result.success
    assert result.data["selected_provider"] == "cap"
    assert recordly.calls == []


def test_explicit_recordly_pick_latest_is_rejected_without_scanning(monkeypatch):
    recordly = FakeProvider("recordly", "recordly_recorder")
    selector = _selector_with(monkeypatch, recordly)
    result = selector.execute(
        {"operation": "pick_latest", "preferred_provider": "recordly"}
    )
    assert not result.success
    assert "explicit input_path" in result.error
    assert recordly.calls == []


def test_cap_status_tracks_real_installation(monkeypatch):
    from tools.capture import cap_recorder as cap_module

    monkeypatch.setattr(cap_module, "_find_cap_binary", lambda: None)
    assert CapRecorder().get_status() == ToolStatus.UNAVAILABLE

    monkeypatch.setattr(cap_module, "_find_cap_binary", lambda: "/Applications/Cap")
    assert CapRecorder().get_status() == ToolStatus.AVAILABLE


def test_screen_recorder_uses_supported_command_dependency_prefix():
    assert ScreenRecorder.dependencies == ["cmd:ffmpeg"]
