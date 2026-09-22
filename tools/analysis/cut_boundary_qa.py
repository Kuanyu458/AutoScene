"""Validate edit-decision cut boundaries against timed transcript words.

The existing final review checks a handful of global timestamps.  This tool
adds footage-led QA at every hard cut: it catches words split by a trim,
reports cuts that are too close to a word edge, and can attach a
``timeline_inspector`` evidence image for human review.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ResumeSupport,
    RetryPolicy,
    ToolResult,
    ToolStability,
    ToolTier,
)
from tools.analysis.editorial_transcript import extract_words
from tools.analysis.timeline_inspector import TimelineInspector


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _load_object(value: Any, path_value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        path_value = value
        value = None
    if value is None and path_value:
        path = Path(path_value)
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _normalise_cuts(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    cuts = decisions.get("cuts") or decisions.get("segments") or []
    if not isinstance(cuts, list):
        raise ValueError("edit_decisions.cuts must be an array")
    normalised: list[dict[str, Any]] = []
    timeline_cursor = 0.0
    for index, raw in enumerate(cuts):
        if not isinstance(raw, dict):
            normalised.append({"id": f"cut-{index:04d}", "invalid": True, "index": index})
            continue
        source = raw.get("source", raw.get("source_id"))
        in_seconds = _number(raw.get("in_seconds", raw.get("start_seconds")), 0.0)
        out_seconds = _number(raw.get("out_seconds", raw.get("end_seconds")), in_seconds)
        speed = max(_number(raw.get("speed"), 1.0), 0.1)
        duration = max(out_seconds - in_seconds, 0.0) / speed
        timeline_start = _number(raw.get("timeline_start_seconds"), timeline_cursor)
        timeline_end = _number(raw.get("timeline_end_seconds"), timeline_start + duration)
        record = {
            **raw,
            "id": str(raw.get("id", f"cut-{index:04d}")),
            "index": index,
            "source": source,
            "in_seconds": in_seconds,
            "out_seconds": out_seconds,
            "speed": speed,
            "timeline_start_seconds": round(timeline_start, 3),
            "timeline_end_seconds": round(timeline_end, 3),
            "invalid": out_seconds <= in_seconds or source in (None, ""),
        }
        normalised.append(record)
        timeline_cursor = timeline_end
    return normalised


def _source_words(transcript: dict[str, Any], source: Any) -> list[dict[str, Any]]:
    """Resolve words for one cut from single- or multi-source transcript shapes."""
    if not transcript:
        return []
    # A convenient multi-source form is {"sources": {"id": {words: [...]}}}.
    sources = transcript.get("sources")
    if isinstance(sources, dict):
        selected = sources.get(str(source))
        if isinstance(selected, dict):
            return extract_words(selected)
    if isinstance(sources, list):
        for entry in sources:
            if isinstance(entry, dict) and str(entry.get("source_id", entry.get("id"))) == str(source):
                return extract_words(entry)
    # An editorial transcript can carry source_id on each word.
    words = extract_words(transcript)
    tagged = [word for word in words if word.get("source_id") not in (None, "")]
    if tagged:
        return [word for word in tagged if str(word.get("source_id")) == str(source)]
    transcript_source = transcript.get("source_id")
    if transcript_source not in (None, "") and str(transcript_source) != str(source):
        return []
    return words


def boundary_issues(
    words: list[dict[str, Any]],
    cut_seconds: float,
    *,
    min_padding_seconds: float = 0.03,
) -> list[dict[str, Any]]:
    """Return deterministic violations/warnings for one source boundary."""
    timed = [
        word for word in words
        if _number(word.get("end")) > _number(word.get("start"))
    ]
    if not timed:
        return [{"code": "no_timed_words", "severity": "warning", "message": "No timed words available for this source"}]

    issues: list[dict[str, Any]] = []
    for word in timed:
        start = _number(word.get("start"))
        end = _number(word.get("end"))
        if start < cut_seconds < end:
            issues.append({
                "code": "split_word",
                "severity": "error",
                "message": f"Cut at {cut_seconds:.3f}s splits word {word.get('text', '')!r}",
                "word": word,
            })

    if not issues:
        nearest = min(
            min(abs(cut_seconds - _number(word.get("start"))), abs(cut_seconds - _number(word.get("end"))))
            for word in timed
        )
        if nearest < min_padding_seconds:
            issues.append({
                "code": "insufficient_padding",
                "severity": "warning",
                "padding_seconds": round(nearest, 3),
                "minimum_padding_seconds": round(min_padding_seconds, 3),
                "message": f"Cut is only {nearest * 1000:.0f}ms from a word boundary",
            })
    return issues


def _resolve_source_path(source: Any, source_paths: Any) -> Optional[Path]:
    if isinstance(source_paths, dict):
        candidate = source_paths.get(str(source))
        if candidate:
            return Path(candidate)
    if isinstance(source, str):
        path = Path(source)
        if path.is_file():
            return path
    return None


class CutBoundaryQA(BaseTool):
    name = "cut_boundary_qa"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = []
    capabilities = ["word_boundary_validation", "cut_coverage", "cut_evidence"]
    input_schema = {
        "type": "object",
        "properties": {
            "edit_decisions": {"type": "object"},
            "edit_decisions_path": {"type": "string"},
            "transcript": {"type": "object"},
            "transcript_path": {"type": "string"},
            "source_paths": {"type": "object", "additionalProperties": {"type": "string"}},
            "min_padding_ms": {"type": "number", "minimum": 0, "default": 30},
            "evidence_dir": {"type": "string"},
            "generate_evidence": {"type": "boolean", "default": True},
            "context_seconds": {"type": "number", "minimum": 0.1, "default": 1.5},
            "output_path": {"type": "string"},
        },
        "anyOf": [{"required": ["edit_decisions"]}, {"required": ["edit_decisions_path"]}],
    }
    output_schema = {"type": "object", "required": ["version", "boundaries", "summary", "status"]}
    artifact_schema = {"name": "cut_review", "version": "1.0"}
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, disk_mb=250)
    retry_policy = RetryPolicy(max_retries=0)
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["edit_decisions_path", "transcript_path", "min_padding_ms", "context_seconds"]
    side_effects = ["writes cut review JSON and optional timeline evidence"]
    user_visible_verification = ["Review every boundary with an error or warning before rendering"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        try:
            decisions = _load_object(inputs.get("edit_decisions"), inputs.get("edit_decisions_path"), "Edit decisions")
            transcript = _load_object(inputs.get("transcript"), inputs.get("transcript_path"), "Transcript")
            cuts = _normalise_cuts(decisions)
            minimum_padding = max(_number(inputs.get("min_padding_ms"), 30.0), 0.0) / 1000.0
            source_paths = inputs.get("source_paths") or {}
            boundaries: list[dict[str, Any]] = []
            for index in range(max(len(cuts) - 1, 0)):
                left = cuts[index]
                right = cuts[index + 1]
                cut_seconds = _number(left.get("out_seconds"))
                issues: list[dict[str, Any]] = []
                if left.get("invalid"):
                    issues.append({"code": "invalid_left_cut", "severity": "error", "message": "Left cut has an invalid source range"})
                if right.get("invalid"):
                    issues.append({"code": "invalid_right_cut", "severity": "error", "message": "Right cut has an invalid source range"})
                words = _source_words(transcript, left.get("source"))
                issues.extend(boundary_issues(words, cut_seconds, min_padding_seconds=minimum_padding))
                boundary: dict[str, Any] = {
                    "id": f"boundary-{index:04d}",
                    "timeline_seconds": round(_number(left.get("timeline_end_seconds")), 3),
                    "source": left.get("source"),
                    "source_seconds": round(cut_seconds, 3),
                    "left_cut_id": left.get("id"),
                    "right_cut_id": right.get("id"),
                    "issues": issues,
                    "status": "fail" if any(issue.get("severity") == "error" for issue in issues) else ("warn" if issues else "pass"),
                }

                if inputs.get("generate_evidence", True):
                    source_path = _resolve_source_path(left.get("source"), source_paths)
                    if source_path and source_path.is_file():
                        evidence_dir = Path(inputs.get("evidence_dir") or source_path.parent / "cut_review")
                        evidence_dir.mkdir(parents=True, exist_ok=True)
                        evidence_path = evidence_dir / f"{boundary['id']}.png"
                        inspector_result = TimelineInspector().execute({
                            "input_path": str(source_path),
                            "start_seconds": max(0.0, cut_seconds - max(_number(inputs.get("context_seconds"), 1.5), 0.1)),
                            "end_seconds": cut_seconds + max(_number(inputs.get("context_seconds"), 1.5), 0.1),
                            "transcript": {"words": words},
                            "output_path": str(evidence_path),
                        })
                        if inspector_result.success:
                            boundary["evidence_path"] = str(evidence_path)
                        else:
                            boundary["evidence_error"] = inspector_result.error
                    elif source_path is not None:
                        boundary["evidence_error"] = f"Source not found: {source_path}"
                    else:
                        boundary["evidence_error"] = "No source path supplied for timeline evidence"
                    if boundary.get("evidence_error") and boundary["status"] == "pass":
                        boundary["status"] = "warn"
                boundaries.append(boundary)

            error_count = sum(1 for boundary in boundaries for issue in boundary["issues"] if issue.get("severity") == "error")
            warning_count = sum(1 for boundary in boundaries for issue in boundary["issues"] if issue.get("severity") == "warning")
            warning_count += sum(1 for boundary in boundaries if boundary.get("evidence_error"))
            artifact = {
                "version": "1.0",
                "edit_decisions_version": decisions.get("version"),
                "boundaries": boundaries,
                "summary": {
                    "checked_boundaries": len(boundaries),
                    "passed_boundaries": sum(1 for boundary in boundaries if boundary["status"] == "pass"),
                    "error_count": error_count,
                    "warning_count": warning_count,
                    "coverage_complete": True,
                    "min_padding_ms": round(minimum_padding * 1000, 3),
                },
                "status": "fail" if error_count else ("needs_review" if warning_count else "pass"),
            }
            output_value = inputs.get("output_path")
            if output_value:
                output_path = Path(output_value)
            elif inputs.get("edit_decisions_path"):
                output_path = Path(inputs["edit_decisions_path"]).with_suffix(".cut_review.json")
            else:
                output_path = Path.cwd() / "cut_review.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return ToolResult(
                success=error_count == 0,
                data=artifact,
                artifacts=[str(output_path)] + [
                    boundary["evidence_path"] for boundary in boundaries if boundary.get("evidence_path")
                ],
                error=(f"{error_count} cut boundary error(s)" if error_count else None),
                duration_seconds=round(time.time() - started, 2),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=str(exc), duration_seconds=round(time.time() - started, 2))
