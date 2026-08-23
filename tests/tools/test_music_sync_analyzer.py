import json
from pathlib import Path

import numpy as np
import soundfile as sf

from schemas.artifacts import validate_artifact
from tools.analysis.music_sync_analyzer import MusicSyncAnalyzer


def _write_click_track(path: Path, bpm: float = 120.0, duration: float = 8.0, silence: float = 0.0) -> None:
    sr = 22050
    samples = np.zeros(int(duration * sr), dtype=np.float32)
    interval = 60.0 / bpm
    for seconds in np.arange(silence, duration, interval):
        start = int(seconds * sr)
        length = min(int(0.025 * sr), len(samples) - start)
        if length > 0:
            envelope = np.exp(-np.arange(length) / (0.004 * sr))
            samples[start:start + length] += (0.95 * envelope).astype(np.float32)
    sf.write(path, samples, sr)


def _write_calm_tone(path: Path, duration: float = 8.0) -> None:
    sr = 22050
    time = np.arange(int(duration * sr)) / sr
    fade = np.minimum(1.0, np.minimum(time / 2.0, (duration - time) / 2.0))
    signal = 0.12 * np.sin(2 * np.pi * 220 * time) * np.maximum(0, fade)
    sf.write(path, signal.astype(np.float32), sr)


def test_120_bpm_map_is_schema_valid_and_deterministic(tmp_path: Path):
    audio = tmp_path / "120bpm.wav"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_click_track(audio)

    tool = MusicSyncAnalyzer()
    result_a = tool.execute({"input_path": str(audio), "output_path": str(first)})
    result_b = tool.execute({"input_path": str(audio), "output_path": str(second)})

    assert result_a.success, result_a.error
    assert result_b.success, result_b.error
    assert first.read_bytes() == second.read_bytes()
    timing_map = json.loads(first.read_text())
    validate_artifact("music_timing_map", timing_map)
    assert 115 <= timing_map["tempo"]["bpm"] <= 125
    assert timing_map["tempo"]["confidence"] >= 0.60
    assert timing_map["tempo"]["grid_reliable"] is True
    assert timing_map["pacing"] == "beat_cut"
    assert timing_map["downbeats"]
    assert any(anchor["type"] == "downbeat" for anchor in timing_map["anchors"])


def test_weak_rhythm_fails_closed_to_phrase_flow(tmp_path: Path):
    audio = tmp_path / "calm.wav"
    output = tmp_path / "calm.json"
    _write_calm_tone(audio)

    result = MusicSyncAnalyzer().execute({"input_path": str(audio), "output_path": str(output)})

    assert result.success, result.error
    timing_map = result.data["timing_map"]
    assert timing_map["tempo"]["confidence"] < 0.60
    assert timing_map["tempo"]["grid_reliable"] is False
    assert timing_map["pacing"] == "phrase_flow"
    assert timing_map["phrases"]


def test_long_intro_silence_does_not_break_analysis(tmp_path: Path):
    audio = tmp_path / "silence-then-clicks.wav"
    output = tmp_path / "map.json"
    _write_click_track(audio, duration=10.0, silence=3.0)

    result = MusicSyncAnalyzer().execute({"input_path": str(audio), "output_path": str(output)})

    assert result.success, result.error
    validate_artifact("music_timing_map", result.data["timing_map"])
    assert result.data["timing_map"]["audio"]["duration_seconds"] == 10.0
