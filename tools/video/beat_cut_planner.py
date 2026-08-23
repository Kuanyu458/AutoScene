"""Section-aware, beat-synced montage planner with a frame-only timeline."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from lib.edit_timeline import music_sync_metrics, validate_timeline_v2
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


class EditPlanError(ValueError):
    """Planning failure with a stable error code and actionable message."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _load_timing_map(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    path = Path(value)
    if not path.is_file():
        raise EditPlanError("TIMING_MAP_MISSING", str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _policy(inputs: dict[str, Any], timing_map: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw = inputs.get("policy", "adaptive")
    options = dict(raw) if isinstance(raw, dict) else {"mode": raw}
    requested = str(options.get("mode", "adaptive"))
    reliable = bool((timing_map.get("tempo") or {}).get("grid_reliable"))
    if not reliable:
        return "phrase_flow", options
    if requested == "phrase_flow":
        return "phrase_flow", options
    return "beat_cut", options


def _ideal_boundaries(timing_map: dict[str, Any], target_frames: int, cut_count: int, fps: int) -> list[int]:
    sections = timing_map.get("sections") or []
    if not sections:
        return [round(target_frames * index / cut_count) for index in range(1, cut_count)]
    spans = []
    total_weight = 0.0
    for section in sections:
        start = max(0, min(target_frames, round(float(section["start_seconds"]) * fps)))
        end = max(start + 1, min(target_frames, round(float(section["end_seconds"]) * fps)))
        quota = max(1.0, float(section.get("recommended_cut_count", 1)))
        weight = quota
        spans.append((start, end, weight))
        total_weight += weight
    if total_weight <= 0:
        return [round(target_frames * index / cut_count) for index in range(1, cut_count)]
    boundaries = []
    for index in range(1, cut_count):
        target_weight = total_weight * index / cut_count
        consumed = 0.0
        frame = round(target_frames * index / cut_count)
        for start, end, weight in spans:
            if consumed + weight >= target_weight:
                ratio = (target_weight - consumed) / weight
                frame = round(start + (end - start) * ratio)
                break
            consumed += weight
        boundaries.append(max(1, min(target_frames - 1, frame)))
    return boundaries


def _candidate_anchors(timing_map: dict[str, Any], mode: str, fps: int, target_frames: int) -> list[dict[str, Any]]:
    allowed = (
        {"downbeat", "phrase", "hard_stop", "energy_change", "pitch_change", "onset", "beat"}
        if mode == "beat_cut"
        else {"phrase", "hard_stop", "energy_change", "pitch_change"}
    )
    candidates = []
    for anchor in timing_map.get("anchors") or []:
        if anchor.get("type") not in allowed:
            continue
        frame = int(round(float(anchor.get("time_seconds", 0)) * fps))
        if 0 < frame < target_frames:
            candidates.append({**anchor, "target_frame": frame})
    return sorted(candidates, key=lambda item: (item["target_frame"], -float(item.get("strength", 0)), str(item.get("id"))))


def _snap_boundaries(
    ideal: list[int],
    candidates: list[dict[str, Any]],
    target_frames: int,
    min_duration: int,
    tolerance: int,
) -> tuple[list[int], dict[int, dict[str, Any]]]:
    selected: list[int] = []
    anchor_by_frame: dict[int, dict[str, Any]] = {}
    for index, desired in enumerate(ideal):
        lower = (selected[-1] if selected else 0) + min_duration
        remaining = len(ideal) - index
        upper = target_frames - remaining * min_duration
        feasible = [
            anchor for anchor in candidates
            if lower <= anchor["target_frame"] <= upper
            and abs(anchor["target_frame"] - desired) <= tolerance
            and anchor["target_frame"] not in anchor_by_frame
        ]
        if feasible:
            chosen = min(feasible, key=lambda anchor: (abs(anchor["target_frame"] - desired), -float(anchor.get("strength", 0)), str(anchor.get("id"))))
            frame = int(chosen["target_frame"])
            anchor_by_frame[frame] = chosen
        else:
            frame = max(lower, min(upper, desired))
        selected.append(frame)
    return selected, anchor_by_frame


def plan_timeline(inputs: dict[str, Any]) -> dict[str, Any]:
    timing_map = _load_timing_map(inputs.get("timing_map"))
    slots = list(inputs.get("slots") or [])
    target_frames = int(inputs.get("target_frames") or 0)
    raw_policy = inputs.get("policy")
    policy_options = raw_policy if isinstance(raw_policy, dict) else {}
    fps = int(policy_options.get("fps", inputs.get("fps", 30)))
    if not slots:
        raise EditPlanError("NO_SLOTS", "At least one source or 3D slot is required")
    if target_frames < len(slots):
        raise EditPlanError("TARGET_TOO_SHORT", "target_frames cannot fit all slots")
    allow_repeat = bool(policy_options.get("allow_repeat", False))
    source_refs = [str(slot.get("source") or slot.get("source_ref") or slot.get("id") or "") for slot in slots]
    if any(not ref for ref in source_refs):
        raise EditPlanError("SLOT_SOURCE_MISSING", "Every slot requires source/source_ref/id")
    if not allow_repeat:
        repeated = sorted({ref for ref in source_refs if source_refs.count(ref) > 1})
        if repeated:
            raise EditPlanError("INSUFFICIENT_UNIQUE_COVERAGE", f"Repeated sources are disabled: {repeated}")

    mode, policy_options = _policy(inputs, timing_map)
    min_duration = int(policy_options.get("min_cut_frames", max(1, round(fps * (0.35 if mode == "beat_cut" else 1.0)))))
    if target_frames < min_duration * len(slots):
        raise EditPlanError(
            "INSUFFICIENT_UNIQUE_COVERAGE",
            f"{len(slots)} slots need at least {min_duration * len(slots)} frames; target is {target_frames}",
        )
    ideal = _ideal_boundaries(timing_map, target_frames, len(slots), fps)
    anchors = _candidate_anchors(timing_map, mode, fps, target_frames)
    tolerance = int(policy_options.get("snap_tolerance_frames", max(fps, round(target_frames / max(1, len(slots)) * 0.45))))
    internal, anchor_by_frame = _snap_boundaries(ideal, anchors, target_frames, min_duration, tolerance)
    boundaries = [0, *internal, target_frames]

    cuts = []
    used_ranges: dict[str, int] = {}
    for index, (slot, source_ref, start, end) in enumerate(zip(slots, source_refs, boundaries, boundaries[1:]), 1):
        duration = end - start
        source_in = int(slot.get("source_in_frame", used_ranges.get(source_ref, 0)))
        available_out = slot.get("source_out_frame")
        if available_out is not None and int(available_out) - source_in < duration:
            raise EditPlanError(
                "INSUFFICIENT_UNIQUE_COVERAGE",
                f"Slot {slot.get('id', index)!r} has {int(available_out) - source_in} source frames but needs {duration}",
            )
        source_out = source_in + duration
        used_ranges[source_ref] = source_out
        cut: dict[str, Any] = {
            "id": str(slot.get("id") or f"cut-{index:03d}"),
            "source": {"ref": source_ref, "in_frame": source_in, "out_frame": source_out},
            "timeline": {"start_frame": start, "end_frame": end},
            "speed": 1.0,
            "presentation": {
                "type": slot.get("type", "video"),
                "kind": slot.get("kind", "source"),
                "reason": slot.get("reason", "section-aware music montage slot"),
                **({"scene_id": slot["scene_id"]} if slot.get("scene_id") else {}),
            },
        }
        if start in anchor_by_frame:
            anchor = anchor_by_frame[start]
            cut["anchor"] = {
                "id": str(anchor["id"]),
                "type": str(anchor["type"]),
                "target_frame": start,
                "error_frames": 0,
            }
        cuts.append(cut)

    metrics = music_sync_metrics(cuts)
    timeline = {
        "version": "2.0",
        "artifact_type": "TimelinePlan",
        "fps": fps,
        "total_frames": target_frames,
        "render_runtime": str(inputs.get("render_runtime", "remotion")),
        "renderer_family": str(inputs.get("renderer_family", "explainer-data")),
        "composition_mode": str(inputs.get("composition_mode", "templated")),
        "cuts": cuts,
        "music_sync": {
            "policy": mode,
            "requested_policy": str(policy_options.get("mode", raw_policy if isinstance(raw_policy, str) else "adaptive")),
            "grid_reliable": bool((timing_map.get("tempo") or {}).get("grid_reliable")),
            "timing_map_sha256": str((timing_map.get("source") or {}).get("sha256", "")),
            **metrics,
        },
        "planner_metrics": {
            "planner": "beat_cut_planner",
            "planner_version": "1.0.0",
            "cut_count": len(cuts),
            "unique_source_count": len(set(source_refs)),
            "gap_frames": 0,
            "overlap_frames": 0,
            "snapped_boundary_count": len(anchor_by_frame),
            "section_quotas": [
                {"section_id": section.get("id"), "recommended_cut_count": section.get("recommended_cut_count", 1)}
                for section in timing_map.get("sections") or []
            ],
        },
    }
    validate_timeline_v2(timeline)
    return timeline


class BeatCutPlanner(BaseTool):
    name = "beat_cut_planner"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    dependencies: list[str] = []
    agent_skills = ["music-to-video", "ffmpeg"]
    capabilities = ["beat_synced_editing", "section_quotas", "timeline_v2", "source_deduplication"]
    input_schema = {
        "type": "object",
        "required": ["timing_map", "slots", "target_frames", "policy"],
        "properties": {
            "timing_map": {"type": ["object", "string"]},
            "slots": {"type": "array", "minItems": 1},
            "target_frames": {"type": "integer", "minimum": 1},
            "policy": {"type": ["string", "object"]},
            "output_path": {"type": "string"},
        },
    }
    output_schema = {"artifact": "edit_decisions", "version": "2.0"}
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=1, network_required=False)
    idempotency_key_fields = ["timing_map", "slots", "target_frames", "policy"]
    side_effects = ["optionally writes TimelinePlan JSON to output_path"]
    best_for = ["prepared media folders with a canonical MusicTimingMap"]
    not_good_for = ["semantic long-form source selection", "inventing repeat/freeze/speed changes"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        try:
            timeline = plan_timeline(inputs)
            output_path = inputs.get("output_path")
            artifacts: list[str] = []
            if output_path:
                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(timeline, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                artifacts.append(str(output.resolve()))
        except EditPlanError as exc:
            return ToolResult(success=False, error=str(exc), data={"code": exc.code, "recoverable": True})
        except Exception as exc:
            return ToolResult(success=False, error=f"EDIT_PLAN_INVALID: {type(exc).__name__}: {exc}", data={"code": "EDIT_PLAN_INVALID"})
        return ToolResult(
            success=True,
            data={"timeline_plan": timeline, "planner_metrics": timeline["planner_metrics"]},
            artifacts=artifacts,
            duration_seconds=round(time.time() - started, 3),
        )
