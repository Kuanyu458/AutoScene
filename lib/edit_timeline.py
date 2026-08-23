"""Canonical frame-based edit timeline contract.

``edit_decisions@2.0`` is the only authoritative timing representation.  Runtime
adapters live here so FFmpeg, Remotion, and HyperFrames cannot independently
reinterpret legacy ``in_seconds`` / ``out_seconds`` fields.
"""

from __future__ import annotations

import copy
import math
from statistics import median
from typing import Any


class TimelineContractError(ValueError):
    """Raised when an edit timeline cannot be normalized without guessing."""


def _frame(value: float | int, fps: int) -> int:
    return int(round(float(value) * fps))


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def music_sync_metrics(cuts: list[dict[str, Any]]) -> dict[str, float | int]:
    """Compute deterministic anchor-error metrics for a normalized timeline."""
    errors = [
        abs(int(cut["anchor"]["error_frames"]))
        for cut in cuts
        if isinstance(cut.get("anchor"), dict)
        and cut["anchor"].get("error_frames") is not None
    ]
    anchored = len(errors)
    return {
        "anchored_cuts": anchored,
        "anchor_coverage": round(anchored / max(1, len(cuts) - 1), 4),
        "median_error_frames": float(median(errors)) if errors else 0.0,
        "p95_error_frames": _percentile(errors, 0.95),
        "max_error_frames": float(max(errors)) if errors else 0.0,
    }


def validate_timeline_v2(timeline: dict[str, Any]) -> None:
    """Validate the cross-runtime timing invariants of TimelineV2."""
    if timeline.get("version") != "2.0":
        raise TimelineContractError("TimelineV2 requires version='2.0'")
    fps = timeline.get("fps")
    total_frames = timeline.get("total_frames")
    if not isinstance(fps, int) or fps <= 0:
        raise TimelineContractError("TimelineV2 fps must be a positive integer")
    if not isinstance(total_frames, int) or total_frames <= 0:
        raise TimelineContractError("TimelineV2 total_frames must be a positive integer")

    cuts = timeline.get("cuts")
    if not isinstance(cuts, list) or not cuts:
        raise TimelineContractError("TimelineV2 requires at least one cut")

    cursor = 0
    ids: set[str] = set()
    for index, cut in enumerate(cuts):
        cut_id = cut.get("id")
        if not isinstance(cut_id, str) or not cut_id:
            raise TimelineContractError(f"cuts[{index}].id must be a non-empty string")
        if cut_id in ids:
            raise TimelineContractError(f"Duplicate cut id: {cut_id}")
        ids.add(cut_id)

        placement = cut.get("timeline") or {}
        source = cut.get("source") or {}
        start = placement.get("start_frame")
        end = placement.get("end_frame")
        source_in = source.get("in_frame")
        source_out = source.get("out_frame")
        source_ref = source.get("ref")
        if not all(isinstance(v, int) for v in (start, end, source_in, source_out)):
            raise TimelineContractError(f"cuts[{index}] timing values must be integer frames")
        if not isinstance(source_ref, str) or not source_ref:
            raise TimelineContractError(f"cuts[{index}].source.ref is required")
        if start != cursor:
            relation = "overlap" if start < cursor else "gap"
            raise TimelineContractError(
                f"Timeline {relation} before cuts[{index}]: expected {cursor}, got {start}"
            )
        if end <= start:
            raise TimelineContractError(f"cuts[{index}] has non-positive timeline duration")
        if source_in < 0 or source_out <= source_in:
            raise TimelineContractError(f"cuts[{index}] has invalid source range")
        speed = float(cut.get("speed", 1.0))
        expected = int(round((source_out - source_in) / speed))
        if abs(expected - (end - start)) > 1:
            raise TimelineContractError(
                f"cuts[{index}] source/timeline durations differ by more than one frame"
            )
        cursor = end

    if cursor != total_frames:
        raise TimelineContractError(
            f"Timeline ends at frame {cursor}; total_frames is {total_frames}"
        )


def normalize_edit_decisions(
    edit_decisions: dict[str, Any],
    *,
    fps: int | None = None,
) -> dict[str, Any]:
    """Normalize edit decisions into the canonical TimelineV2 shape.

    Legacy v1 artifacts use Remotion's established semantics: ``in_seconds`` /
    ``out_seconds`` place the cut on the final timeline, while optional
    ``source_in_seconds`` selects the source trim.  This rule is centralized
    here and recorded in ``normalization`` so migration is never implicit.
    """
    version = str(edit_decisions.get("version", "1.0"))
    if version == "2.0":
        normalized = copy.deepcopy(edit_decisions)
        validate_timeline_v2(normalized)
        return normalized
    if version != "1.0":
        raise TimelineContractError(f"Unsupported edit_decisions version: {version}")

    resolved_fps = int(fps or edit_decisions.get("fps") or 30)
    if resolved_fps <= 0:
        raise TimelineContractError("fps must be positive")
    legacy_cuts = edit_decisions.get("cuts") or []
    if not legacy_cuts:
        raise TimelineContractError("Legacy edit_decisions has no cuts")

    cuts: list[dict[str, Any]] = []
    for index, legacy in enumerate(legacy_cuts):
        start = _frame(legacy.get("in_seconds", 0), resolved_fps)
        end = _frame(legacy.get("out_seconds", 0), resolved_fps)
        source_in = _frame(legacy.get("source_in_seconds", 0), resolved_fps)
        duration = end - start
        if duration <= 0:
            raise TimelineContractError(f"Legacy cut {index} has non-positive duration")
        speed = float(legacy.get("speed", 1.0))
        source_out = source_in + int(round(duration * speed))
        presentation = {
            key: copy.deepcopy(value)
            for key, value in legacy.items()
            if key not in {
                "id", "source", "in_seconds", "out_seconds",
                "source_in_seconds", "speed", "anchor",
            }
        }
        cut: dict[str, Any] = {
            "id": str(legacy.get("id") or f"cut-{index + 1}"),
            "source": {
                "ref": str(legacy.get("source") or ""),
                "in_frame": source_in,
                "out_frame": source_out,
            },
            "timeline": {"start_frame": start, "end_frame": end},
            "speed": speed,
        }
        if legacy.get("anchor"):
            cut["anchor"] = copy.deepcopy(legacy["anchor"])
        if presentation:
            cut["presentation"] = presentation
        cuts.append(cut)

    normalized: dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in edit_decisions.items()
        if key not in {"version", "cuts", "fps", "total_frames", "music_sync"}
    }
    normalized.update({
        "version": "2.0",
        "fps": resolved_fps,
        "total_frames": max(c["timeline"]["end_frame"] for c in cuts),
        "cuts": cuts,
        "music_sync": {
            "policy": "legacy_unsynced",
            "grid_reliable": False,
            **music_sync_metrics(cuts),
        },
        "normalization": {
            "from_version": "1.0",
            "legacy_semantics": "timeline_in_out_with_optional_source_in",
        },
    })
    validate_timeline_v2(normalized)
    return normalized


def adapt_timeline_for_runtime(
    edit_decisions: dict[str, Any],
    runtime: str,
) -> dict[str, Any]:
    """Return legacy-shaped cuts with runtime-specific timing semantics."""
    timeline = normalize_edit_decisions(edit_decisions)
    runtime_name = runtime.lower()
    if runtime_name not in {"ffmpeg", "remotion", "hyperframes"}:
        raise TimelineContractError(f"Unsupported runtime adapter: {runtime}")
    fps = timeline["fps"]
    adapted = copy.deepcopy(timeline)
    adapted["version"] = "2.0-runtime-adapter"
    adapted["timeline_version"] = "2.0"
    adapted_cuts: list[dict[str, Any]] = []
    for cut in timeline["cuts"]:
        placement = cut["timeline"]
        source = cut["source"]
        presentation = copy.deepcopy(cut.get("presentation") or {})
        result = {
            "id": cut["id"],
            "source": source["ref"],
            "speed": cut.get("speed", 1.0),
            **presentation,
        }
        if runtime_name == "ffmpeg":
            result["in_seconds"] = source["in_frame"] / fps
            result["out_seconds"] = source["out_frame"] / fps
            result["timeline_start_seconds"] = placement["start_frame"] / fps
            result["timeline_end_seconds"] = placement["end_frame"] / fps
        else:
            result["in_seconds"] = placement["start_frame"] / fps
            result["out_seconds"] = placement["end_frame"] / fps
            result["source_in_seconds"] = source["in_frame"] / fps
            result["source_out_seconds"] = source["out_frame"] / fps
        if cut.get("anchor"):
            result["anchor"] = copy.deepcopy(cut["anchor"])
        adapted_cuts.append(result)
    adapted["cuts"] = adapted_cuts
    adapted["runtime_adapter"] = runtime_name
    return adapted
