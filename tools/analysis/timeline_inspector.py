"""Generate a filmstrip/waveform/word timeline composite for editorial QA.

This is intentionally a small, deterministic inspection surface rather than
a second renderer.  It samples a bounded source range, draws silence bands and
word labels from an editorial transcript, and writes an evidence image plus a
JSON sidecar that an agent or reviewer can inspect later.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
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


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load_transcript(inputs: dict[str, Any]) -> dict[str, Any]:
    transcript = inputs.get("transcript")
    if isinstance(transcript, str):
        transcript = json.loads(Path(transcript).read_text(encoding="utf-8"))
    elif transcript is None and inputs.get("transcript_path"):
        transcript = json.loads(Path(inputs["transcript_path"]).read_text(encoding="utf-8"))
    if transcript is None:
        return {}
    if not isinstance(transcript, dict):
        raise ValueError("Transcript must be a JSON object")
    return transcript


def compute_silence_bands(
    words: list[dict[str, Any]],
    start: float,
    end: float,
    *,
    minimum_gap_seconds: float = 0.4,
) -> list[dict[str, float]]:
    """Return leading, inter-word, and trailing gaps worth showing."""
    timed = sorted(
        (word for word in words if word.get("end", 0) > word.get("start", 0)),
        key=lambda word: (float(word["start"]), float(word["end"])),
    )
    clipped: list[tuple[float, float]] = []
    for word in timed:
        word_start = max(start, _finite_number(word.get("start")))
        word_end = min(end, _finite_number(word.get("end")))
        if word_end > word_start:
            clipped.append((word_start, word_end))

    bands: list[dict[str, float]] = []
    cursor = start
    for word_start, word_end in clipped:
        if word_start - cursor >= minimum_gap_seconds:
            bands.append({"start": round(cursor, 3), "end": round(word_start, 3), "duration": round(word_start - cursor, 3)})
        cursor = max(cursor, word_end)
    if end - cursor >= minimum_gap_seconds:
        bands.append({"start": round(cursor, 3), "end": round(end, 3), "duration": round(end - cursor, 3)})
    return bands


def _range_words(words: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [
        word for word in words
        if _finite_number(word.get("end")) > start and _finite_number(word.get("start")) < end
    ]


def _even_timestamps(start: float, end: float, count: int) -> list[float]:
    count = max(1, min(int(count), 24))
    duration = max(end - start, 0.001)
    return [round(start + duration * ((index + 0.5) / count), 3) for index in range(count)]


def _safe_name(value: float) -> str:
    return f"{value:.3f}".replace(".", "_")


class TimelineInspector(BaseTool):
    name = "timeline_inspector"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "ffmpeg"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe", "python:PIL"]
    install_instructions = "Install FFmpeg and Pillow: pip install Pillow"
    agent_skills = ["ffmpeg"]
    capabilities = [
        "filmstrip",
        "waveform",
        "word_timeline",
        "silence_bands",
        "cut_boundary_evidence",
    ]
    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string"},
            "start_seconds": {"type": "number", "minimum": 0, "default": 0},
            "end_seconds": {"type": "number", "minimum": 0},
            "sample_count": {"type": "integer", "minimum": 1, "maximum": 24, "default": 8},
            "transcript_path": {"type": "string"},
            "transcript": {"type": "object"},
            "minimum_silence_seconds": {"type": "number", "minimum": 0, "default": 0.4},
            "output_path": {"type": "string"},
        },
    }
    output_schema = {
        "type": "object",
        "required": ["input_path", "range", "frames", "words", "silence_bands", "output_path"],
    }
    artifact_schema = {"name": "timeline_inspection", "version": "1.0"}
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, disk_mb=250)
    retry_policy = RetryPolicy(max_retries=0)
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["input_path", "start_seconds", "end_seconds", "sample_count", "transcript_path", "minimum_silence_seconds"]
    side_effects = ["writes timeline evidence PNG and JSON sidecar"]
    user_visible_verification = ["Inspect filmstrip, waveform, word labels, and silence bands around the edit boundary"]

    def get_status(self):
        # Keep BaseTool's dependency check, but expose a useful status when
        # Pillow is importable under a different module alias on Windows.
        return super().get_status()

    def _get_duration(self, input_path: Path) -> float:
        result = self.run_command([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(input_path),
        ], timeout=60)
        return max(_finite_number(result.stdout.strip()), 0.0)

    def _extract_frame(self, input_path: Path, timestamp: float, output_path: Path) -> bool:
        try:
            self.run_command([
                "ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(input_path),
                "-frames:v", "1", "-q:v", "3", str(output_path),
            ], timeout=120)
        except Exception:
            return False
        return output_path.is_file() and output_path.stat().st_size > 0

    def _extract_waveform(self, input_path: Path, start: float, duration: float, output_path: Path) -> bool:
        if duration <= 0:
            return False
        try:
            self.run_command([
                "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                "-i", str(input_path), "-filter_complex",
                "[0:a]showwavespic=s=1600x240:colors=0x5eead4[wave]",
                "-map", "[wave]", "-frames:v", "1", str(output_path),
            ], timeout=120)
        except Exception:
            return False
        return output_path.is_file() and output_path.stat().st_size > 0

    @staticmethod
    def _draw_composite(
        frame_paths: list[tuple[float, Path]],
        waveform_path: Optional[Path],
        words: list[dict[str, Any]],
        silence_bands: list[dict[str, float]],
        start: float,
        end: float,
        output_path: Path,
    ) -> None:
        from PIL import Image, ImageDraw, ImageFont, ImageOps

        width = 1600
        tile_width = max(1, width // max(len(frame_paths), 1))
        tile_height = 250
        timeline_height = 105
        waveform_height = 240
        footer_height = 100
        canvas = Image.new("RGB", (width, tile_height + timeline_height + waveform_height + footer_height), "#111827")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()

        for index, (timestamp, path) in enumerate(frame_paths):
            left = index * tile_width
            right = width if index == len(frame_paths) - 1 else (index + 1) * tile_width
            try:
                image = Image.open(path).convert("RGB")
                image = ImageOps.fit(image, (right - left, tile_height - 26), method=Image.Resampling.LANCZOS)
                canvas.paste(image, (left, 0))
            except Exception:
                draw.rectangle((left, 0, right, tile_height - 26), fill="#374151")
            draw.rectangle((left, tile_height - 26, right, tile_height), fill="#111827")
            draw.text((left + 6, tile_height - 18), f"{timestamp:.3f}s", fill="#d1d5db", font=font)

        timeline_top = tile_height
        draw.rectangle((0, timeline_top, width, timeline_top + timeline_height), fill="#1f2937")
        duration = max(end - start, 0.001)
        for band in silence_bands:
            x1 = int((band["start"] - start) / duration * width)
            x2 = int((band["end"] - start) / duration * width)
            draw.rectangle((x1, timeline_top, max(x1 + 1, x2), timeline_top + timeline_height), fill="#374151")
        draw.text((8, timeline_top + 5), "silence", fill="#9ca3af", font=font)
        for word in words:
            word_start = max(start, _finite_number(word.get("start")))
            word_end = min(end, _finite_number(word.get("end")))
            if word_end <= word_start:
                continue
            x1 = int((word_start - start) / duration * width)
            x2 = int((word_end - start) / duration * width)
            y1 = timeline_top + 28
            y2 = timeline_top + 62
            draw.rounded_rectangle((x1, y1, max(x1 + 2, x2), y2), radius=3, fill="#0f766e", outline="#99f6e4")
            label = str(word.get("text", ""))
            if x2 - x1 > 28:
                draw.text((x1 + 3, y1 + 10), label[:18], fill="#ecfeff", font=font)
        draw.line((0, timeline_top + timeline_height - 18, width, timeline_top + timeline_height - 18), fill="#6b7280")
        draw.text((8, timeline_top + timeline_height - 15), f"{start:.3f}s", fill="#d1d5db", font=font)
        end_label = f"{end:.3f}s"
        draw.text((width - 8 - len(end_label) * 6, timeline_top + timeline_height - 15), end_label, fill="#d1d5db", font=font)

        waveform_top = timeline_top + timeline_height
        if waveform_path and waveform_path.is_file():
            try:
                waveform = Image.open(waveform_path).convert("RGB")
                waveform = ImageOps.fit(waveform, (width, waveform_height), method=Image.Resampling.LANCZOS)
                canvas.paste(waveform, (0, waveform_top))
            except Exception:
                draw.rectangle((0, waveform_top, width, waveform_top + waveform_height), fill="#111827")
        else:
            draw.rectangle((0, waveform_top, width, waveform_top + waveform_height), fill="#111827")
            draw.text((8, waveform_top + 8), "no audio waveform available", fill="#9ca3af", font=font)

        footer_top = waveform_top + waveform_height
        draw.rectangle((0, footer_top, width, footer_top + footer_height), fill="#111827")
        snippets = []
        for word in words:
            text = str(word.get("text", "")).strip()
            if text:
                snippets.append(text)
        summary = " ".join(snippets)
        if len(summary) > 240:
            summary = summary[:237] + "..."
        draw.text((8, footer_top + 10), summary or "(no timed words in range)", fill="#e5e7eb", font=font)
        draw.text((8, footer_top + 38), f"{len(words)} words | {len(silence_bands)} silence bands | range {start:.3f}-{end:.3f}s", fill="#9ca3af", font=font)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG", optimize=True)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        input_path = Path(inputs["input_path"])
        if not input_path.is_file():
            return ToolResult(success=False, error=f"Input not found: {input_path}")

        temp_dir: Optional[Path] = None
        try:
            duration = self._get_duration(input_path)
            start = max(0.0, _finite_number(inputs.get("start_seconds"), 0.0))
            requested_end = inputs.get("end_seconds")
            end = _finite_number(requested_end, duration) if requested_end is not None else duration
            if duration > 0:
                end = min(end, duration)
            if end <= start:
                end = min(max(start + 0.001, duration), start + max(duration, 0.001))
            transcript = _load_transcript(inputs)
            words = _range_words(extract_words(transcript), start, end)
            min_gap = max(_finite_number(inputs.get("minimum_silence_seconds"), 0.4), 0.0)
            silence_bands = compute_silence_bands(words, start, end, minimum_gap_seconds=min_gap)

            output_path = Path(inputs["output_path"]) if inputs.get("output_path") else (
                input_path.parent / "timeline_inspection" / f"timeline_{_safe_name(start)}_{_safe_name(end)}.png"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix="timeline_", dir=str(output_path.parent)))
            frame_paths: list[tuple[float, Path]] = []
            for index, timestamp in enumerate(_even_timestamps(start, end, inputs.get("sample_count", 8))):
                frame_path = temp_dir / f"frame_{index:03d}.jpg"
                if self._extract_frame(input_path, timestamp, frame_path):
                    frame_paths.append((timestamp, frame_path))

            waveform_path = temp_dir / "waveform.png"
            if not self._extract_waveform(input_path, start, end - start, waveform_path):
                waveform_path = None
            self._draw_composite(frame_paths, waveform_path, words, silence_bands, start, end, output_path)

            # Frame paths are part of the evidence contract, so keep copies
            # outside the temporary render directory before it is removed.
            persistent_frames = output_path.parent / f"{output_path.stem}_frames"
            persistent_frame_records: list[dict[str, Any]] = []
            if frame_paths:
                persistent_frames.mkdir(parents=True, exist_ok=True)
            for index, (timestamp, path) in enumerate(frame_paths):
                target = persistent_frames / f"frame_{index:03d}.jpg"
                shutil.copy2(path, target)
                persistent_frame_records.append({"timestamp_seconds": timestamp, "path": str(target)})

            sidecar = output_path.with_suffix(".json")
            data = {
                "version": "1.0",
                "input_path": str(input_path),
                "range": {"start_seconds": round(start, 3), "end_seconds": round(end, 3)},
                "frames": persistent_frame_records,
                "words": words,
                "silence_bands": silence_bands,
                "waveform_available": waveform_path is not None,
                "output_path": str(output_path),
            }
            sidecar.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return ToolResult(
                success=True,
                data=data,
                artifacts=[str(output_path), str(sidecar)] + [
                    record["path"] for record in persistent_frame_records
                ],
                duration_seconds=round(time.time() - started, 2),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=str(exc), duration_seconds=round(time.time() - started, 2))
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
