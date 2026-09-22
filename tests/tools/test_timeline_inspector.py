from pathlib import Path

from PIL import Image

from tools.analysis.timeline_inspector import TimelineInspector


def test_timeline_inspector_persists_frame_evidence(tmp_path, monkeypatch):
    input_path = tmp_path / "take.mp4"
    input_path.write_bytes(b"fixture")
    tool = TimelineInspector()
    monkeypatch.setattr(tool, "_get_duration", lambda _path: 4.0)

    def fake_frame(_input, _timestamp, output):
        Image.new("RGB", (32, 18), (20, 80, 90)).save(output, format="JPEG")
        return True

    def fake_wave(_input, _start, _duration, output):
        Image.new("RGB", (80, 20), (10, 20, 30)).save(output, format="PNG")
        return True

    monkeypatch.setattr(tool, "_extract_frame", fake_frame)
    monkeypatch.setattr(tool, "_extract_waveform", fake_wave)
    result = tool.execute({
        "input_path": str(input_path),
        "start_seconds": 1.0,
        "end_seconds": 3.0,
        "sample_count": 2,
        "transcript": {"word_timestamps": [
            {"start": 1.2, "end": 1.5, "word": "hello"},
            {"start": 2.1, "end": 2.4, "word": "world"},
        ]},
        "output_path": str(tmp_path / "evidence" / "timeline.png"),
    })
    assert result.success, result.error
    assert Path(result.data["output_path"]).is_file()
    assert Path(result.data["output_path"]).with_suffix(".json").is_file()
    assert result.data["waveform_available"] is True
    assert result.data["frames"]
    assert all(Path(frame["path"]).is_file() for frame in result.data["frames"])
