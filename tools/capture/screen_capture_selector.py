"""Capability-level screen capture selector.

The selector is the stable seam used by the screen-demo pipeline. Concrete
providers own their capture workflow: FFmpeg records synchronously, while Cap
and Recordly are user-operated GUIs. Recordly captures are ingested only from
an MP4 path explicitly selected by the user; this module never searches its
private files or pretends that launching the GUI completed a recording.
"""

from __future__ import annotations

from typing import Any

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


class ScreenCaptureSelector(BaseTool):
    name = "screen_capture_selector"
    version = "0.2.0"
    tier = ToolTier.SOURCE
    capability = "screen_capture"
    provider = "selector"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.HYBRID

    # `screen-demo` named the Layer 2 pipeline directory, not a Layer 3 skill,
    # so it never resolved. No Layer 3 skill covers OS screen capture — the
    # capture guidance this selector needs lives in the pipeline manifest's
    # per-stage `skill:` entries (skills/pipelines/screen-demo/), which the
    # agent already reads.
    capabilities = [
        "screen_recording",
        "provider_selection",
        "interactive_capture_preparation",
        "explicit_capture_ingest",
        "capture_setup_guidance",
    ]
    best_for = [
        "Choosing a capture provider without exposing provider setup to the pipeline",
        "Routing automated FFmpeg capture and polished user-guided product demos",
        "Preparing and ingesting explicitly selected Recordly exports",
    ]
    not_good_for = [
        "Driving private GUI automation or searching a user's recording folders",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["recommend", "record", "pick_latest", "prepare", "ingest"],
                "description": (
                    "recommend compares providers; record runs direct capture or prepares a GUI; "
                    "prepare launches or explains a GUI workflow; ingest imports one explicit "
                    "Recordly MP4; pick_latest checks Cap only"
                ),
            },
            "preferred_provider": {
                "type": "string",
                "enum": ["auto", "ffmpeg", "cap", "recordly"],
                "default": "auto",
            },
            "capture_intent": {
                "type": "string",
                "enum": ["automated", "polished_product_demo"],
                "default": "automated",
                "description": (
                    "automated preserves FFmpeg as the auto default; polished_product_demo "
                    "prefers an available Recordly or Cap GUI"
                ),
            },
            "output_path": {
                "type": "string",
                "description": "Output MP4 path for direct FFmpeg recording.",
            },
            "duration_seconds": {"type": "integer", "default": 60},
            "fps": {"type": "integer", "default": 30},
            "capture_audio": {"type": "boolean", "default": True},
            "region": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
            },
            "screen_index": {"type": "integer", "default": 0},
            "since_minutes": {"type": "integer", "default": 5},
            "application_path": {
                "type": "string",
                "description": "Optional explicit Recordly executable or macOS app path.",
            },
            "input_path": {
                "type": "string",
                "description": "Explicit Recordly-exported MP4 for ingest.",
            },
            "output_dir": {
                "type": "string",
                "description": "New or empty Recordly capture-package directory for ingest.",
            },
            "privacy_review": {
                "type": "string",
                "enum": ["pending", "passed", "blocked"],
                "default": "pending",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "recommended_provider": {"type": "string"},
            "options": {"type": "array"},
            "state": {"type": "string"},
            "status": {"type": "string"},
            "selected_provider": {"type": "string"},
            "selected_tool": {"type": "string"},
            "output_path": {"type": "string"},
            "capture_method": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=64, vram_mb=0, disk_mb=0, network_required=False
    )
    side_effects = ["may_create_file", "may_launch_external_gui"]

    def _providers(self) -> dict[str, BaseTool]:
        """Auto-discover providers keyed by their public provider identifier."""
        from tools.tool_registry import registry

        registry.ensure_discovered()
        return {
            tool.provider: tool
            for tool in registry.get_by_capability("screen_capture")
            if tool.name != self.name
        }

    @property
    def fallback_tools(self) -> list[str]:
        """Registry fallback references are tool names, never provider IDs."""
        return [tool.name for tool in self._providers().values()]

    def get_status(self) -> ToolStatus:
        statuses = [tool.get_status() for tool in self._providers().values()]
        if ToolStatus.AVAILABLE in statuses:
            return ToolStatus.AVAILABLE
        if ToolStatus.DEGRADED in statuses:
            return ToolStatus.DEGRADED
        return ToolStatus.UNAVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation")
        if operation == "recommend":
            return self._recommend(inputs)
        if operation == "record":
            return self._record(inputs)
        if operation == "prepare":
            return self._prepare(inputs)
        if operation == "ingest":
            return self._ingest(inputs)
        if operation == "pick_latest":
            return self._pick_latest(inputs)
        return ToolResult(
            success=False,
            error=(
                f"Unknown operation: {operation}. Valid: recommend, record, prepare, "
                "ingest, pick_latest"
            ),
        )

    @staticmethod
    def _recordly_doctor(tool: BaseTool, inputs: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {"operation": "doctor"}
        if inputs.get("application_path"):
            request["application_path"] = inputs["application_path"]
        result = tool.execute(request)
        return result.data if result.success else {}

    @classmethod
    def _recordly_live_ready(cls, tool: BaseTool, inputs: dict[str, Any]) -> bool:
        doctor = cls._recordly_doctor(tool, inputs)
        installed = bool(doctor.get("installed"))
        platform_ready = bool(doctor.get("platform_supported", True))
        recording_ready = bool(
            doctor.get("recording_ready", doctor.get("capture_state") == "ready")
        )
        return installed and platform_ready and recording_ready

    def _options(self, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        providers = self._providers()
        options: list[dict[str, Any]] = []

        ffmpeg = providers.get("ffmpeg")
        if ffmpeg:
            available = ffmpeg.get_status() == ToolStatus.AVAILABLE
            options.append(
                {
                    "provider": "ffmpeg",
                    "tool": ffmpeg.name,
                    "label": "Quick Recording (FFmpeg)",
                    "available": available,
                    "setup_required": not available,
                    "workflow": "automated",
                    "strengths": ["Direct CLI recording", "Full screen or region capture"],
                    "limitations": ["No recorder-side cursor effects or editor"],
                    "best_when": "You need deterministic automated capture",
                }
            )

        cap = providers.get("cap")
        if cap:
            detected = cap.execute({"operation": "detect"})
            data = detected.data if detected.success else {}
            installed = bool(data.get("installed"))
            running = bool(data.get("running"))
            options.append(
                {
                    "provider": "cap",
                    "tool": cap.name,
                    "label": "Pro Recording (Cap)",
                    "available": installed,
                    "running": running,
                    "status": "Running" if running else ("Installed" if installed else "Not installed"),
                    "setup_required": not installed,
                    "workflow": "user_guided",
                    "strengths": ["Webcam overlay", "Cursor effects", "Built-in editor"],
                    "limitations": ["Recording is a human-operated step"],
                    "best_when": "You want a polished user-guided capture",
                }
            )

        recordly = providers.get("recordly")
        if recordly:
            doctor = self._recordly_doctor(recordly, inputs)
            installed = bool(doctor.get("installed"))
            recording_ready = self._recordly_live_ready(recordly, inputs)
            options.append(
                {
                    "provider": "recordly",
                    "tool": recordly.name,
                    "label": "Product UI Recording (Recordly)",
                    # Live capture readiness differs from portable ingest readiness.
                    "available": recording_ready,
                    "installed": installed,
                    "ingest_available": bool(doctor.get("ingest_ready")),
                    "status": "Installed" if installed else "Not installed",
                    "setup_required": not recording_ready,
                    "workflow": "user_guided_explicit_ingest",
                    "strengths": [
                        "Polished product UI workflow",
                        "Explicit project-owned MP4 ingest with provenance",
                    ],
                    "limitations": ["Recording and export require human interaction"],
                    "best_when": "You want a polished product UI demo",
                }
            )

        return options

    @staticmethod
    def _recommended_provider(inputs: dict[str, Any], options: list[dict[str, Any]]) -> str:
        preferred = inputs.get("preferred_provider", "auto")
        if preferred != "auto":
            # Keep an explicit choice visible even when it still needs setup.
            return str(preferred)

        order = (
            ("recordly", "cap", "ffmpeg")
            if inputs.get("capture_intent", "automated") == "polished_product_demo"
            else ("ffmpeg", "cap", "recordly")
        )
        for provider in order:
            option = next((item for item in options if item["provider"] == provider), None)
            if option and option.get("available"):
                return provider
        return "ffmpeg"

    def _recommend(self, inputs: dict[str, Any]) -> ToolResult:
        options = self._options(inputs)
        recommended = self._recommended_provider(inputs, options)
        return ToolResult(
            success=True,
            data={
                "recommended_provider": recommended,
                "capture_intent": inputs.get("capture_intent", "automated"),
                "options": options,
                "message": self._build_recommendation_message(recommended, options),
            },
        )

    @staticmethod
    def _build_recommendation_message(recommended: str, options: list[dict[str, Any]]) -> str:
        lines = ["**Screen Recording Options:**", ""]
        for index, option in enumerate(options, start=1):
            status = option.get("status") or (
                "Ready" if option.get("available") else "Setup required"
            )
            lines.append(f"**Option {index} — {option['label']}** [{status}]")
            lines.append(f"  {option['best_when']}.")
        lines.extend(["", f"**Recommended:** {recommended}"])
        return "\n".join(lines)

    @staticmethod
    def _unavailable(provider: str, tool: BaseTool | None = None) -> ToolResult:
        detail = f" {tool.install_instructions}" if tool and tool.install_instructions else ""
        return ToolResult(
            success=False,
            data={
                "state": "blocked",
                "status": "blocked",
                "selected_provider": provider,
                "selected_tool": tool.name if tool else None,
            },
            error=f"Explicitly selected screen capture provider '{provider}' is unavailable.{detail}",
        )

    def _record(self, inputs: dict[str, Any]) -> ToolResult:
        providers = self._providers()
        preferred = inputs.get("preferred_provider", "auto")

        if preferred == "recordly":
            tool = providers.get("recordly")
            return self._prepare_recordly(tool, inputs) if tool else self._unavailable("recordly")

        if preferred == "ffmpeg":
            tool = providers.get("ffmpeg")
            if not tool or tool.get_status() != ToolStatus.AVAILABLE:
                return self._unavailable("ffmpeg", tool)
            return self._record_ffmpeg(tool, inputs)

        if preferred == "cap":
            tool = providers.get("cap")
            return self._prepare_cap(tool) if tool else self._unavailable("cap")

        options = self._options(inputs)
        selected = self._recommended_provider(inputs, options)
        if selected == "recordly" and providers.get("recordly"):
            return self._prepare_recordly(providers["recordly"], inputs)
        if selected == "cap" and providers.get("cap"):
            return self._prepare_cap(providers["cap"])
        ffmpeg = providers.get("ffmpeg")
        if ffmpeg and ffmpeg.get_status() == ToolStatus.AVAILABLE:
            return self._record_ffmpeg(ffmpeg, inputs)
        return ToolResult(
            success=False,
            data={"state": "blocked", "status": "blocked"},
            error="No live screen capture provider is available.",
        )

    @staticmethod
    def _record_ffmpeg(tool: BaseTool, inputs: dict[str, Any]) -> ToolResult:
        result = tool.execute(
            {
                "output_path": inputs.get("output_path", "recording.mp4"),
                "duration_seconds": inputs.get("duration_seconds", 60),
                "fps": inputs.get("fps", 30),
                "capture_audio": inputs.get("capture_audio", True),
                "region": inputs.get("region"),
                "screen_index": inputs.get("screen_index", 0),
            }
        )
        if result.success:
            result.data.setdefault("selected_provider", "ffmpeg")
            result.data.setdefault("selected_tool", tool.name)
            result.data.setdefault("state", "captured")
        return result

    def _prepare(self, inputs: dict[str, Any]) -> ToolResult:
        providers = self._providers()
        preferred = inputs.get("preferred_provider", "auto")

        if preferred == "recordly":
            tool = providers.get("recordly")
            return self._prepare_recordly(tool, inputs) if tool else self._unavailable("recordly")
        if preferred == "cap":
            tool = providers.get("cap")
            return self._prepare_cap(tool) if tool else self._unavailable("cap")
        if preferred == "ffmpeg":
            tool = providers.get("ffmpeg")
            if not tool or tool.get_status() != ToolStatus.AVAILABLE:
                return self._unavailable("ffmpeg", tool)
            return ToolResult(
                success=True,
                data={
                    "state": "ready",
                    "status": "ready",
                    "selected_provider": "ffmpeg",
                    "selected_tool": tool.name,
                    "next_step": "Call operation='record' with output_path and duration_seconds.",
                },
            )

        selected = self._recommended_provider(inputs, self._options(inputs))
        delegated = dict(inputs)
        delegated["preferred_provider"] = selected
        return self._prepare(delegated)

    @staticmethod
    def _prepare_cap(tool: BaseTool) -> ToolResult:
        """Return a manual setup/recording gate; never reuse an old capture as new."""
        guide = tool.execute({"operation": "setup_guide"})
        if guide.success:
            guide.data.update(
                {
                    "state": "awaiting_human",
                    "status": "awaiting_human",
                    "capture_state": (
                        "ready_for_human_recording"
                        if tool.get_status() == ToolStatus.AVAILABLE
                        else "setup_required"
                    ),
                    "selected_provider": "cap",
                    "selected_tool": tool.name,
                    "requires_human_action": True,
                    "next_step": guide.data.get(
                        "next_step",
                        "Record in Cap, then call operation='pick_latest' explicitly.",
                    ),
                }
            )
        return guide

    def _prepare_recordly(
        self, tool: BaseTool | None, inputs: dict[str, Any]
    ) -> ToolResult:
        if tool is None:
            return self._unavailable("recordly")

        doctor_request: dict[str, Any] = {"operation": "doctor"}
        if inputs.get("application_path"):
            doctor_request["application_path"] = inputs["application_path"]
        doctor_result = tool.execute(doctor_request)
        doctor = doctor_result.data if doctor_result.success else {}

        if not self._recordly_live_ready(tool, inputs):
            guide = tool.execute({"operation": "setup_guide"})
            if not guide.success:
                return guide
            data = dict(guide.data)
            data.update(
                {
                    "state": "awaiting_human",
                    "status": "awaiting_human",
                    "capture_state": "setup_required",
                    "selected_provider": "recordly",
                    "selected_tool": tool.name,
                    "requires_human_action": True,
                    "doctor": doctor,
                }
            )
            return ToolResult(success=True, data=data)

        launch_request: dict[str, Any] = {"operation": "launch"}
        if inputs.get("application_path"):
            launch_request["application_path"] = inputs["application_path"]
        launched = tool.execute(launch_request)
        if not launched.success:
            return launched
        data = dict(launched.data)
        # A GUI launch is never a completed recording.
        data.update(
            {
                "state": "awaiting_human",
                "status": "awaiting_human",
                "capture_state": "awaiting_human",
                "selected_provider": "recordly",
                "selected_tool": tool.name,
                "requires_human_action": True,
            }
        )
        return ToolResult(success=True, data=data, artifacts=list(launched.artifacts))

    def _ingest(self, inputs: dict[str, Any]) -> ToolResult:
        preferred = inputs.get("preferred_provider", "auto")
        if preferred not in {"auto", "recordly"}:
            return ToolResult(
                success=False,
                error="operation='ingest' is supported only by the Recordly adapter",
            )
        tool = self._providers().get("recordly")
        if tool is None:
            return self._unavailable("recordly")

        # App installation is not required for portable ingest; ffprobe is the
        # actual dependency and the provider returns the precise blocker.
        request: dict[str, Any] = {
            "operation": "ingest",
            "input_path": inputs.get("input_path"),
            "output_dir": inputs.get("output_dir"),
            "privacy_review": inputs.get("privacy_review", "pending"),
        }
        result = tool.execute(request)
        if result.success:
            result.data.setdefault("state", "ingested")
            result.data.setdefault("selected_provider", "recordly")
            result.data.setdefault("selected_tool", tool.name)
        return result

    def _pick_latest(self, inputs: dict[str, Any]) -> ToolResult:
        if inputs.get("preferred_provider", "auto") == "recordly":
            return ToolResult(
                success=False,
                error=(
                    "Recordly recordings are never discovered with pick_latest. "
                    "Use operation='ingest' with an explicit input_path."
                ),
            )

        cap = self._providers().get("cap")
        if cap:
            result = cap.execute(
                {
                    "operation": "find_recordings",
                    "since_minutes": inputs.get("since_minutes", 5),
                }
            )
            if result.success and result.data.get("recordings"):
                latest = result.data["recordings"][0]
                return ToolResult(
                    success=True,
                    data={
                        "output_path": latest["path"],
                        "size_mb": latest["size_mb"],
                        "capture_method": "cap",
                        "selected_provider": "cap",
                        "selected_tool": cap.name,
                        "source": "cap_recordings_dir",
                    },
                    artifacts=[latest["path"]],
                )

        return ToolResult(
            success=False,
            error=(
                "No recent Cap recordings found. Recordly requires an explicit "
                "operation='ingest' input_path and is not scanned."
            ),
        )
