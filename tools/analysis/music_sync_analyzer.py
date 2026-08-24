"""Deterministic single-pass music structure analysis for beat-synced editing."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

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


ANALYZER_VERSION = "1.0.0"
SAMPLE_RATE = 22_050
HOP_LENGTH = 512
ANALYSIS_FPS = 30
GRID_CONFIDENCE_THRESHOLD = 0.60


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _point(seconds: float) -> dict[str, Any]:
    return {"time_seconds": _round(seconds), "frame_30": int(round(seconds * ANALYSIS_FPS))}


def _level(value: float) -> str:
    if value < 0.08:
        return "void"
    if value < 0.35:
        return "low"
    if value < 0.68:
        return "medium"
    return "high"


def _normalize(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values.astype(float)
    peak = float(np.max(values))
    return values.astype(float) / peak if peak > 1e-12 else np.zeros_like(values, dtype=float)


def _local_peaks(values: np.ndarray, threshold: float, minimum_gap: int) -> list[int]:
    candidates = [
        index for index in range(1, max(1, len(values) - 1))
        if values[index] >= threshold
        and values[index] >= values[index - 1]
        and values[index] >= values[index + 1]
    ]
    selected: list[int] = []
    for index in sorted(candidates, key=lambda item: (-float(values[item]), item)):
        if all(abs(index - other) >= minimum_gap for other in selected):
            selected.append(index)
    return sorted(selected)


def _tempo_confidence(
    beats_seconds: np.ndarray,
    beat_frames: np.ndarray,
    onset_envelope: np.ndarray,
    onset_count: int,
    duration: float,
) -> float:
    if len(beats_seconds) < 4 or onset_count < 4 or onset_envelope.size == 0:
        return 0.0
    intervals = np.diff(beats_seconds)
    mean_interval = float(np.mean(intervals))
    if mean_interval <= 0:
        return 0.0
    consistency = max(0.0, 1.0 - float(np.std(intervals) / mean_interval) / 0.18)
    valid_frames = beat_frames[(beat_frames >= 0) & (beat_frames < len(onset_envelope))]
    reference = float(np.percentile(onset_envelope, 90)) + 1e-9
    pulse_strength = min(1.0, float(np.mean(onset_envelope[valid_frames])) / reference) if len(valid_frames) else 0.0
    density = min(1.0, onset_count / max(4.0, duration * 1.25))
    dynamic = min(1.0, float(np.std(onset_envelope)) / (float(np.mean(onset_envelope)) + 1e-9))
    return _round(max(0.0, min(1.0, 0.45 * consistency + 0.30 * pulse_strength + 0.15 * density + 0.10 * dynamic)), 4)


def _energy_spans(y: np.ndarray, sr: int, duration: float) -> list[dict[str, Any]]:
    window = max(1, sr // 2)
    values: list[float] = []
    for start in range(0, len(y), window):
        segment = y[start:start + window]
        values.append(float(np.sqrt(np.mean(np.square(segment), dtype=np.float64))) if len(segment) else 0.0)
    normalized = _normalize(np.asarray(values))
    spans = []
    for index, value in enumerate(normalized):
        start = index * 0.5
        end = min(duration, (index + 1) * 0.5)
        if end > start:
            spans.append({
                "start_seconds": _round(start),
                "end_seconds": _round(end),
                "level": _level(float(value)),
                "value": _round(value, 4),
            })
    return spans


def _hard_stops(energy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stops = []
    for index in range(1, len(energy)):
        previous = float(energy[index - 1]["value"])
        current = float(energy[index]["value"])
        next_value = float(energy[index + 1]["value"]) if index + 1 < len(energy) else current
        if previous >= 0.35 and current <= 0.08 and next_value <= 0.12:
            stops.append(_point(float(energy[index]["start_seconds"])))
    return stops


def _derive_phrases(
    downbeats: list[dict[str, Any]],
    energy: list[dict[str, Any]],
    duration: float,
    grid_reliable: bool,
) -> list[dict[str, Any]]:
    boundaries = [0.0]
    if grid_reliable and len(downbeats) >= 2:
        boundaries.extend(float(point["time_seconds"]) for point in downbeats[4::4])
    else:
        last = 0.0
        for index in range(1, len(energy)):
            time_seconds = float(energy[index]["start_seconds"])
            delta = abs(float(energy[index]["value"]) - float(energy[index - 1]["value"]))
            if delta >= 0.28 and time_seconds - last >= 3.0:
                boundaries.append(time_seconds)
                last = time_seconds
        cursor = 8.0
        while cursor < duration:
            if all(abs(cursor - boundary) >= 2.0 for boundary in boundaries):
                boundaries.append(cursor)
            cursor += 8.0
    boundaries.append(duration)
    boundaries = sorted(set(_round(max(0.0, min(duration, value))) for value in boundaries))
    phrases = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        if end - start <= 1e-6:
            continue
        bars = 4 if grid_reliable else 0
        phrases.append({"id": f"phrase-{index:03d}", "start_seconds": start, "end_seconds": end, "bars": bars})
    return phrases


def _derive_sections(
    phrases: list[dict[str, Any]],
    energy: list[dict[str, Any]],
    onsets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sections = []
    for index, phrase in enumerate(phrases, 1):
        start = float(phrase["start_seconds"])
        end = float(phrase["end_seconds"])
        energy_values = [float(item["value"]) for item in energy if item["start_seconds"] < end and item["end_seconds"] > start]
        mean_energy = float(np.mean(energy_values)) if energy_values else 0.0
        onset_count = sum(1 for item in onsets if start <= float(item["time_seconds"]) < end)
        density_rate = onset_count / max(0.001, end - start)
        density = "sparse" if density_rate < 0.8 else "dense" if density_rate >= 2.5 else "medium"
        cut_seconds = 3.5 if density == "sparse" else 1.5 if density == "dense" else 2.5
        sections.append({
            "id": f"section-{index:03d}",
            "start_seconds": _round(start),
            "end_seconds": _round(end),
            "energy": _round(mean_energy, 4),
            "density": density,
            "recommended_cut_count": max(1, int(round((end - start) / cut_seconds))),
        })
    return sections


def _section_for_time(sections: list[dict[str, Any]], seconds: float) -> str | None:
    for section in sections:
        if section["start_seconds"] <= seconds < section["end_seconds"] + 1e-6:
            return str(section["id"])
    return None


def _anchors(
    *,
    beats: list[dict[str, Any]],
    downbeats: list[dict[str, Any]],
    onsets: list[dict[str, Any]],
    pitch_changes: list[dict[str, Any]],
    energy: list[dict[str, Any]],
    phrases: list[dict[str, Any]],
    hard_stops: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, float, str, float]] = []
    for point in beats:
        candidates.append((point["frame_30"], 0.35, "beat", point["time_seconds"]))
    for point in downbeats:
        candidates.append((point["frame_30"], 0.72, "downbeat", point["time_seconds"]))
    for point in onsets:
        candidates.append((point["frame_30"], 0.45 + 0.35 * point["strength"], "onset", point["time_seconds"]))
    for point in pitch_changes:
        candidates.append((point["frame_30"], 0.55 + 0.25 * point["strength"], "pitch_change", point["time_seconds"]))
    for index in range(1, len(energy)):
        delta = abs(float(energy[index]["value"]) - float(energy[index - 1]["value"]))
        if delta >= 0.25:
            seconds = float(energy[index]["start_seconds"])
            candidates.append((int(round(seconds * ANALYSIS_FPS)), min(1.0, 0.5 + delta / 2), "energy_change", seconds))
    for phrase in phrases[1:]:
        seconds = float(phrase["start_seconds"])
        candidates.append((int(round(seconds * ANALYSIS_FPS)), 0.86, "phrase", seconds))
    for point in hard_stops:
        candidates.append((point["frame_30"], 1.0, "hard_stop", point["time_seconds"]))

    priority = {"hard_stop": 7, "phrase": 6, "energy_change": 5, "downbeat": 4, "pitch_change": 3, "onset": 2, "beat": 1}
    selected: list[tuple[int, float, str, float]] = []
    for candidate in sorted(candidates, key=lambda item: (-priority[item[2]], -item[1], item[0], item[2])):
        if all(abs(candidate[0] - existing[0]) > 1 for existing in selected):
            selected.append(candidate)
    selected.sort(key=lambda item: (item[0], -priority[item[2]], item[2]))
    counters: dict[str, int] = {}
    result = []
    for frame, strength, kind, seconds in selected:
        counters[kind] = counters.get(kind, 0) + 1
        result.append({
            "id": f"{kind}-{counters[kind]:04d}",
            "type": kind,
            "time_seconds": _round(seconds),
            "frame_30": int(frame),
            "strength": _round(min(1.0, strength), 4),
            **({"section_id": section_id} if (section_id := _section_for_time(sections, seconds)) else {}),
        })
    return result


def analyze_music(path: Path) -> dict[str, Any]:
    """Analyze one file and return a schema-valid MusicTimingMap payload."""
    import soundfile as sf

    try:
        y, source_sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            decoded = Path(handle.name)
        try:
            completed = subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), str(decoded)],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode != 0:
                raise ValueError(completed.stderr[-1600:])
            y, source_sr = sf.read(str(decoded), dtype="float32", always_2d=False)
        finally:
            decoded.unlink(missing_ok=True)
    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = np.mean(y, axis=1, dtype=np.float32)
    if int(source_sr) != SAMPLE_RATE and y.size:
        new_length = max(1, int(round(len(y) * SAMPLE_RATE / int(source_sr))))
        source_axis = np.linspace(0.0, 1.0, len(y), endpoint=False)
        target_axis = np.linspace(0.0, 1.0, new_length, endpoint=False)
        y = np.interp(target_axis, source_axis, y).astype(np.float32)
    sr = SAMPLE_RATE
    if y.size == 0:
        raise ValueError("Decoded audio is empty")
    duration = len(y) / sr

    frame_size = 2048
    if len(y) < frame_size:
        y = np.pad(y, (0, frame_size - len(y)))
    frame_count = 1 + (len(y) - frame_size) // HOP_LENGTH
    frames = np.stack(
        [y[index * HOP_LENGTH:index * HOP_LENGTH + frame_size] for index in range(frame_count)],
        axis=0,
    )
    spectra = np.abs(np.fft.rfft(frames * np.hanning(frame_size), axis=1))
    positive_flux = np.maximum(0.0, np.diff(spectra, axis=0, prepend=spectra[:1]))
    onset_envelope = _normalize(np.sum(positive_flux, axis=1))
    onset_threshold = max(0.12, float(np.median(onset_envelope) + 0.65 * np.std(onset_envelope)))
    onset_frames = np.asarray(
        _local_peaks(
            onset_envelope,
            onset_threshold,
            max(2, int(round(0.12 * sr / HOP_LENGTH))),
        ),
        dtype=int,
    )
    onset_times = onset_frames * HOP_LENGTH / sr

    beat_frames = np.asarray([], dtype=int)
    bpm = 0.0
    if len(onset_frames) >= 4 and np.max(onset_envelope) > 1e-6:
        centered = onset_envelope - np.mean(onset_envelope)
        autocorrelation = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
        envelope_rate = sr / HOP_LENGTH
        min_lag = max(1, int(math.floor(envelope_rate * 60 / 180)))
        max_lag = min(len(autocorrelation) - 1, int(math.ceil(envelope_rate * 60 / 60)))
        if max_lag > min_lag:
            lag_scores = autocorrelation[min_lag:max_lag + 1] / np.maximum(1, len(centered) - np.arange(min_lag, max_lag + 1))
            period = min_lag + int(np.argmax(lag_scores))
            # Autocorrelation often chooses the one-bar/half-tempo harmonic.
            # Prefer the double-tempo pulse only when its subdivision is also
            # strongly present; this keeps genuine 60-80 BPM material intact.
            half_period = max(min_lag, int(round(period / 2)))
            if period > half_period and 60.0 * envelope_rate / period < 90:
                full_score = float(autocorrelation[period]) / max(1, len(centered) - period)
                half_score = float(autocorrelation[half_period]) / max(1, len(centered) - half_period)
                if half_score >= full_score * 0.45:
                    period = half_period
            bpm = 60.0 * envelope_rate / period
            phase = int(onset_frames[int(np.argmax(onset_envelope[onset_frames]))])
            predicted = list(range(phase, len(onset_envelope), period))
            predicted = list(range(phase - period, -1, -period))[::-1] + predicted
            aligned = []
            search = max(1, min(3, period // 4))
            for frame in predicted:
                lo, hi = max(0, frame - search), min(len(onset_envelope), frame + search + 1)
                candidate = lo + int(np.argmax(onset_envelope[lo:hi]))
                if not aligned or candidate > aligned[-1]:
                    aligned.append(candidate)
            beat_frames = np.asarray(aligned, dtype=int)
    beat_times = beat_frames * HOP_LENGTH / sr
    confidence = _tempo_confidence(beat_times, beat_frames, onset_envelope, len(onset_frames), duration)
    grid_reliable = bool(confidence >= GRID_CONFIDENCE_THRESHOLD and len(beat_times) >= 4)

    onset_norm = _normalize(onset_envelope)
    onsets = [
        {**_point(float(seconds)), "strength": _round(onset_norm[min(int(frame), len(onset_norm) - 1)], 4)}
        for seconds, frame in zip(onset_times, onset_frames)
        if 0 <= seconds <= duration
    ]
    beats = [_point(float(seconds)) for seconds in beat_times if 0 <= seconds <= duration]

    downbeat_offset = 0
    if grid_reliable and len(beat_frames) >= 4:
        scores = []
        for phase in range(4):
            indices = beat_frames[phase::4]
            valid = indices[(indices >= 0) & (indices < len(onset_envelope))]
            scores.append(float(np.mean(onset_envelope[valid])) if len(valid) else 0.0)
        downbeat_offset = int(np.argmax(scores))
    downbeats = [_point(float(beat_times[index])) for index in range(downbeat_offset, len(beat_times), 4)] if grid_reliable else []

    frequencies = np.fft.rfftfreq(frame_size, 1 / sr)
    centroid = np.sum(spectra * frequencies[None, :], axis=1) / (np.sum(spectra, axis=1) + 1e-9)
    novelty = _normalize(np.abs(np.diff(centroid, prepend=centroid[:1])))
    threshold = max(0.35, float(np.percentile(novelty, 90))) if novelty.size else 1.0
    pitch_peak_frames = _local_peaks(novelty, threshold, max(1, int(0.35 * sr / HOP_LENGTH)))
    pitch_changes = [
        {**_point(float(frame * HOP_LENGTH / sr)), "strength": _round(novelty[frame], 4)}
        for frame in pitch_peak_frames
        if frame * HOP_LENGTH / sr <= duration
    ]

    energy = _energy_spans(y, sr, duration)
    hard_stops = _hard_stops(energy)
    phrases = _derive_phrases(downbeats, energy, duration, grid_reliable)
    sections = _derive_sections(phrases, energy, onsets)
    anchors = _anchors(
        beats=beats,
        downbeats=downbeats,
        onsets=onsets,
        pitch_changes=pitch_changes,
        energy=energy,
        phrases=phrases,
        hard_stops=hard_stops,
        sections=sections,
    )
    return {
        "version": "1.0",
        "analyzer": {"name": "music_sync_analyzer", "version": ANALYZER_VERSION, "sample_rate": SAMPLE_RATE, "hop_length": HOP_LENGTH},
        "source": {"path": str(path.resolve()), "sha256": _sha256(path), "size_bytes": path.stat().st_size},
        "audio": {"duration_seconds": _round(duration), "duration_frames_30": max(1, int(round(duration * ANALYSIS_FPS))), "sample_rate": sr},
        "tempo": {"bpm": _round(bpm, 3), "confidence": confidence, "grid_reliable": grid_reliable, "beats_per_bar": 4},
        "pacing": "beat_cut" if grid_reliable else "phrase_flow",
        "beats": beats,
        "downbeats": downbeats,
        "onsets": onsets,
        "pitch_changes": pitch_changes,
        "energy": energy,
        "phrases": phrases,
        "hard_stops": hard_stops,
        "sections": sections,
        "anchors": anchors,
        "metadata": {
            "confidence_threshold": GRID_CONFIDENCE_THRESHOLD,
            "analysis_fps": ANALYSIS_FPS,
            "dsp": "numpy_spectral_flux_autocorrelation",
            "librosa_contract_version": "1.0.0",
        },
    }


class MusicSyncAnalyzer(BaseTool):
    name = "music_sync_analyzer"
    version = ANALYZER_VERSION
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    dependencies = ["python:librosa", "python:soundfile"]
    install_instructions = "pip install librosa==1.0.0 soundfile==0.14.0"
    agent_skills = ["music-to-video"]
    capabilities = ["music_timing_map", "beat_grid", "phrase_analysis", "energy_sections", "edit_anchors"]
    input_schema = {
        "type": "object",
        "required": ["input_path", "output_path"],
        "properties": {"input_path": {"type": "string"}, "output_path": {"type": "string"}},
        "additionalProperties": False,
    }
    output_schema = {"artifact": "music_timing_map", "version": "1.0"}
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=100, network_required=False)
    idempotency_key_fields = ["input_path"]
    side_effects = ["writes MusicTimingMap JSON to output_path"]
    best_for = ["single-pass deterministic music analysis for montage editing"]
    not_good_for = ["claiming a precise beat grid for ambient or weakly rhythmic music"]
    user_visible_verification = ["Inspect tempo confidence and pacing before authoring cuts"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs.get("input_path", "")).expanduser()
        output = Path(inputs.get("output_path", "")).expanduser()
        if not source.is_file():
            return ToolResult(success=False, error=f"Input audio not found: {source}")
        if not output.name:
            return ToolResult(success=False, error="output_path is required")
        started = time.time()
        try:
            timing_map = analyze_music(source)
            from schemas.artifacts import validate_artifact

            validate_artifact("music_timing_map", timing_map)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(timing_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Music analysis failed: {type(exc).__name__}: {exc}")
        return ToolResult(
            success=True,
            data={"timing_map": timing_map, "output_path": str(output.resolve())},
            artifacts=[str(output.resolve())],
            duration_seconds=round(time.time() - started, 3),
        )
