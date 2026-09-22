"""Shared authoring model for agent edits and the future Backlot editor.

The module deliberately contains no browser or rendering code.  It converts
the existing ``edit_decisions`` artifact into a revisioned timeline and
applies a small, auditable set of UI operations before handing the result
back to the canonical composition runtime.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from schemas.artifacts import validate_artifact


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _segment_from_cut(cut: dict[str, Any], index: int, cursor: float) -> tuple[dict[str, Any], float]:
    source_in = max(_number(cut.get("in_seconds", cut.get("start_seconds"))), 0.0)
    source_out = max(_number(cut.get("out_seconds", cut.get("end_seconds")), source_in), 0.0)
    speed = max(_number(cut.get("speed"), 1.0), 0.1)
    duration = max(source_out - source_in, 0.0) / speed
    start = max(_number(cut.get("timeline_start_seconds"), cursor), 0.0)
    end = max(_number(cut.get("timeline_end_seconds"), start + duration), start)
    segment = {
        "id": str(cut.get("id", f"cut-{index:04d}")),
        "source": str(cut.get("source", "")),
        "source_in_seconds": round(source_in, 3),
        "source_out_seconds": round(source_out, 3),
        "timeline_start_seconds": round(start, 3),
        "timeline_end_seconds": round(end, 3),
        "speed": speed,
    }
    for key in ("transition_in", "transition_out", "transform", "reason"):
        if cut.get(key) is not None:
            segment[key] = deepcopy(cut[key])
    return segment, end


def normalize_edit_decisions(edit_decisions: dict[str, Any], *, revision: int = 0) -> dict[str, Any]:
    """Convert legacy/current ``cuts`` into the shared edit timeline shape."""
    if not isinstance(edit_decisions, dict):
        raise ValueError("edit_decisions must be an object")
    cuts = edit_decisions.get("cuts") or []
    if not isinstance(cuts, list):
        raise ValueError("edit_decisions.cuts must be an array")

    segments: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    cursor = 0.0
    for index, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            raise ValueError(f"edit_decisions.cuts[{index}] must be an object")
        segment, cursor = _segment_from_cut(cut, index, cursor)
        if not segment["source"]:
            raise ValueError(f"edit_decisions.cuts[{index}] is missing source")
        segments.append(segment)
        source_ids.add(segment["source"])

    sources = []
    manifest = edit_decisions.get("sources") or edit_decisions.get("source_manifest") or []
    if isinstance(manifest, list):
        for source in manifest:
            if isinstance(source, dict) and source.get("id"):
                sources.append(deepcopy(source))
    known_sources = {str(source.get("id")) for source in sources}
    for source_id in sorted(source_ids - known_sources):
        sources.append({"id": source_id})

    # Keep renderer-only decisions beside the authoring fields.  The Backlot
    # API stores only edit_timeline, so a later render must not lose subtitles,
    # audio, overlays, bespoke settings, or automation evidence.
    preserved_decisions = deepcopy(edit_decisions)
    for key in (
        "version",
        "cuts",
        "segments",
        "sources",
        "source_manifest",
        "zoom_keyframes",
        "audio_tracks",
        "overlays",
        "render_runtime",
        "renderer_family",
        "composition_mode",
        "canvas",
        "visual_layers",
        "camera_tracks",
        "studio_asset_manifest",
    ):
        preserved_decisions.pop(key, None)

    timeline = {
        "version": "1.0",
        "revision": max(int(revision), 0),
        "sources": sources,
        "segments": segments,
        "zoom_keyframes": deepcopy(edit_decisions.get("zoom_keyframes") or []),
        "audio_tracks": deepcopy(edit_decisions.get("audio_tracks") or []),
        "overlays": deepcopy(edit_decisions.get("overlays") or []),
        "canvas": deepcopy(edit_decisions.get("canvas") or {
            "width": 1920,
            "height": 1080,
            "coordinate_space": "normalized",
        }),
        "visual_layers": deepcopy(edit_decisions.get("visual_layers") or []),
        "camera_tracks": deepcopy(edit_decisions.get("camera_tracks") or []),
        "asset_manifest": deepcopy(edit_decisions.get("studio_asset_manifest") or []),
        "metadata": {
            "render_runtime": edit_decisions.get("render_runtime"),
            "renderer_family": edit_decisions.get("renderer_family"),
            "composition_mode": edit_decisions.get("composition_mode"),
            "base_edit_decisions": preserved_decisions,
            "origin": "edit_decisions",
        },
    }
    validate_artifact("edit_timeline", timeline)
    return timeline


def _find_segment(timeline: dict[str, Any], segment_id: str) -> dict[str, Any]:
    for segment in timeline.get("segments", []):
        if str(segment.get("id")) == str(segment_id):
            return segment
    raise ValueError(f"Unknown segment_id: {segment_id}")


def _find_layer(timeline: dict[str, Any], layer_id: str) -> dict[str, Any]:
    for layer in timeline.get("visual_layers", []):
        if str(layer.get("id")) == str(layer_id):
            return layer
    raise ValueError(f"Unknown visual layer id: {layer_id}")


def _find_camera_track(timeline: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    for track in timeline.get("camera_tracks", []):
        if str(track.get("id")) == str(track_id):
            return track
    return None


def _merge_object(target: dict[str, Any], patch: dict[str, Any]) -> None:
    """Merge one level of authoring fields while replacing nested objects atomically."""
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    for key, value in patch.items():
        target[key] = deepcopy(value)


def resequence_segments(timeline: dict[str, Any]) -> None:
    """Recompute timeline positions after trim/reorder without changing source ranges."""
    cursor = 0.0
    for segment in timeline.get("segments", []):
        source_duration = max(
            _number(segment.get("source_out_seconds")) - _number(segment.get("source_in_seconds")),
            0.0,
        )
        speed = max(_number(segment.get("speed"), 1.0), 0.1)
        duration = source_duration / speed
        segment["timeline_start_seconds"] = round(cursor, 3)
        cursor += duration
        segment["timeline_end_seconds"] = round(cursor, 3)


def apply_timeline_operations(
    timeline: dict[str, Any],
    operations: Iterable[dict[str, Any]],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Apply auditable editor operations and return a new revision.

    Supported operations include the legacy trim/reorder/zoom operations and
    semantic visual-layer/camera operations. Unknown operations fail closed so
    a UI cannot silently lose an edit that the renderer does not understand.
    """
    if not isinstance(timeline, dict):
        raise ValueError("timeline must be an object")
    current_revision = int(timeline.get("revision", 0))
    if expected_revision is not None and current_revision != int(expected_revision):
        raise ValueError(f"revision conflict: expected {expected_revision}, found {current_revision}")
    updated = deepcopy(timeline)
    zoom_keyframes = updated.setdefault("zoom_keyframes", [])
    visual_layers = updated.setdefault("visual_layers", [])
    camera_tracks = updated.setdefault("camera_tracks", [])
    asset_manifest = updated.setdefault("asset_manifest", [])
    needs_resequence = False

    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("timeline operation must be an object")
        kind = operation.get("op")
        if kind == "trim":
            segment = _find_segment(updated, str(operation.get("segment_id", "")))
            source_in = max(_number(operation.get("source_in_seconds"), _number(segment.get("source_in_seconds"))), 0.0)
            source_out = max(_number(operation.get("source_out_seconds"), _number(segment.get("source_out_seconds"))), 0.0)
            if source_out <= source_in:
                raise ValueError("trim source_out_seconds must be greater than source_in_seconds")
            segment["source_in_seconds"] = round(source_in, 3)
            segment["source_out_seconds"] = round(source_out, 3)
            needs_resequence = True
        elif kind == "reorder":
            requested = [str(value) for value in operation.get("segment_ids", [])]
            current = [str(segment.get("id")) for segment in updated.get("segments", [])]
            if sorted(requested) != sorted(current) or len(requested) != len(current):
                raise ValueError("reorder segment_ids must contain each existing segment exactly once")
            by_id = {str(segment["id"]): segment for segment in updated["segments"]}
            updated["segments"] = [by_id[segment_id] for segment_id in requested]
            needs_resequence = True
        elif kind == "set_zoom_keyframe":
            segment_id = str(operation.get("segment_id", ""))
            _find_segment(updated, segment_id)
            time_seconds = max(_number(operation.get("time_seconds")), 0.0)
            keyframe = {
                "segment_id": segment_id,
                "time_seconds": round(time_seconds, 3),
                "scale": max(_number(operation.get("scale"), 1.0), 1.0),
                "x": min(max(_number(operation.get("x"), 0.5), 0.0), 1.0),
                "y": min(max(_number(operation.get("y"), 0.5), 0.0), 1.0),
                "easing": str(operation.get("easing", "linear")),
            }
            zoom_keyframes[:] = [
                item for item in zoom_keyframes
                if not (str(item.get("segment_id")) == segment_id and abs(_number(item.get("time_seconds")) - time_seconds) < 0.001)
            ]
            zoom_keyframes.append(keyframe)
        elif kind == "remove_zoom_keyframe":
            segment_id = str(operation.get("segment_id", ""))
            time_seconds = _number(operation.get("time_seconds"))
            zoom_keyframes[:] = [
                item for item in zoom_keyframes
                if not (str(item.get("segment_id")) == segment_id and abs(_number(item.get("time_seconds")) - time_seconds) < 0.001)
            ]
        elif kind == "add_visual_layer":
            layer = operation.get("layer")
            if not isinstance(layer, dict):
                raise ValueError("add_visual_layer requires a layer object")
            layer = deepcopy(layer)
            layer_id = str(layer.get("id", ""))
            if not layer_id:
                raise ValueError("visual layer id is required")
            if any(str(item.get("id")) == layer_id for item in visual_layers):
                raise ValueError(f"visual layer already exists: {layer_id}")
            _find_segment(updated, str(layer.get("segment_id", "")))
            visual_layers.append(layer)
        elif kind == "update_visual_layer":
            layer = _find_layer(updated, str(operation.get("layer_id", "")))
            patch = operation.get("patch")
            _merge_object(layer, patch)
            if "segment_id" in patch:
                _find_segment(updated, str(layer.get("segment_id", "")))
        elif kind == "remove_visual_layer":
            layer_id = str(operation.get("layer_id", ""))
            before = len(visual_layers)
            visual_layers[:] = [item for item in visual_layers if str(item.get("id")) != layer_id]
            if len(visual_layers) == before:
                raise ValueError(f"Unknown visual layer id: {layer_id}")
        elif kind == "reorder_visual_layers":
            segment_id = str(operation.get("segment_id", ""))
            requested = [str(value) for value in operation.get("layer_ids", [])]
            current = [str(item.get("id")) for item in visual_layers if str(item.get("segment_id")) == segment_id]
            if sorted(requested) != sorted(current) or len(requested) != len(current):
                raise ValueError("reorder layer_ids must contain each segment layer exactly once")
            z_by_id = {layer_id: index for index, layer_id in enumerate(requested)}
            for item in visual_layers:
                if str(item.get("id")) in z_by_id:
                    item["z_index"] = z_by_id[str(item["id"])]
        elif kind == "set_camera_keyframe":
            segment_id = str(operation.get("segment_id", ""))
            _find_segment(updated, segment_id)
            track_id = str(operation.get("camera_track_id") or f"camera-{segment_id}")
            track = _find_camera_track(updated, track_id)
            if track is None:
                track = {"id": track_id, "segment_id": segment_id, "keyframes": []}
                camera_tracks.append(track)
            elif str(track.get("segment_id")) != segment_id:
                raise ValueError("camera track segment_id cannot change")
            keyframe = {
                "time_seconds": round(max(_number(operation.get("time_seconds")), 0.0), 3),
                "position": [float(value) for value in operation.get("position", [0, 0, 5])],
                "target": [float(value) for value in operation.get("target", [0, 0, 0])],
                "fov": min(max(_number(operation.get("fov"), 45.0), 2.0), 179.0),
                "easing": str(operation.get("easing", "linear")),
            }
            if len(keyframe["position"]) != 3 or len(keyframe["target"]) != 3:
                raise ValueError("camera position and target must have three coordinates")
            track["keyframes"] = [
                item for item in track.get("keyframes", [])
                if abs(_number(item.get("time_seconds")) - keyframe["time_seconds"]) >= 0.001
            ]
            track["keyframes"].append(keyframe)
            track["keyframes"].sort(key=lambda item: _number(item.get("time_seconds")))
        elif kind == "remove_camera_keyframe":
            track_id = str(operation.get("camera_track_id", ""))
            track = _find_camera_track(updated, track_id)
            if track is None:
                raise ValueError(f"Unknown camera track id: {track_id}")
            time_seconds = _number(operation.get("time_seconds"))
            track["keyframes"] = [
                item for item in track.get("keyframes", [])
                if abs(_number(item.get("time_seconds")) - time_seconds) >= 0.001
            ]
        elif kind == "attach_asset":
            asset = operation.get("asset")
            if not isinstance(asset, dict) or not asset.get("id"):
                raise ValueError("attach_asset requires an asset with id")
            asset = deepcopy(asset)
            asset_id = str(asset["id"])
            if any(str(item.get("id")) == asset_id for item in asset_manifest):
                raise ValueError(f"asset already exists: {asset_id}")
            asset_manifest.append(asset)
        elif kind == "remove_asset":
            asset_id = str(operation.get("asset_id", ""))
            before = len(asset_manifest)
            asset_manifest[:] = [item for item in asset_manifest if str(item.get("id")) != asset_id]
            if len(asset_manifest) == before:
                raise ValueError(f"Unknown asset id: {asset_id}")
        else:
            raise ValueError(f"Unsupported timeline operation: {kind}")

    if needs_resequence:
        resequence_segments(updated)
    updated["revision"] = current_revision + 1
    validate_artifact("edit_timeline", updated)
    return updated


def timeline_to_edit_decisions(
    timeline: dict[str, Any],
    *,
    base_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert an authoring timeline into the existing renderer input shape."""
    if not isinstance(timeline, dict):
        raise ValueError("timeline must be an object")
    validate_artifact("edit_timeline", timeline)
    timeline_metadata = timeline.get("metadata") or {}
    stored_base = timeline_metadata.get("base_edit_decisions") if isinstance(timeline_metadata, dict) else None
    if isinstance(base_decisions, dict):
        decisions = deepcopy(base_decisions)
    elif isinstance(stored_base, dict):
        decisions = deepcopy(stored_base)
    else:
        decisions = {"version": "1.0", "cuts": []}
    decisions["version"] = "1.0"
    cuts: list[dict[str, Any]] = []
    for segment in timeline.get("segments", []):
        cut = {
            "id": str(segment["id"]),
            "source": str(segment["source"]),
            "in_seconds": round(_number(segment["source_in_seconds"]), 3),
            "out_seconds": round(_number(segment["source_out_seconds"]), 3),
            "speed": max(_number(segment.get("speed"), 1.0), 0.1),
        }
        for key in ("transition_in", "transition_out", "transform", "reason"):
            if segment.get(key) is not None:
                cut[key] = deepcopy(segment[key])
        cuts.append(cut)
    decisions["cuts"] = cuts
    if isinstance(timeline.get("overlays"), list):
        decisions["overlays"] = deepcopy(timeline["overlays"])
    for key in ("canvas", "visual_layers", "camera_tracks"):
        if isinstance(timeline.get(key), (dict, list)):
            decisions[key] = deepcopy(timeline[key])
    if isinstance(timeline.get("asset_manifest"), list):
        decisions["studio_asset_manifest"] = deepcopy(timeline["asset_manifest"])
    if isinstance(timeline.get("zoom_keyframes"), list):
        decisions["zoom_keyframes"] = deepcopy(timeline["zoom_keyframes"])
    metadata = decisions.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        decisions["metadata"] = metadata
    if isinstance(timeline_metadata, dict):
        for key in ("render_runtime", "renderer_family", "composition_mode"):
            if timeline_metadata.get(key) is not None:
                decisions[key] = timeline_metadata[key]
    metadata["edit_timeline_revision"] = int(timeline.get("revision", 0))
    metadata["edit_timeline_version"] = timeline.get("version")
    return decisions
