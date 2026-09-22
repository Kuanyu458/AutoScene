import json

import pytest

from lib.edit_timeline import apply_timeline_operations, normalize_edit_decisions
from schemas.artifacts import validate_artifact
from tools.analysis.cut_boundary_qa import CutBoundaryQA, boundary_issues
from tools.analysis.editorial_transcript import EditorialTranscript, join_tokens, pack_phrases


def _words():
    return [
        {"start": 0.0, "end": 0.35, "word": "Hello", "speaker": "A"},
        {"start": 0.40, "end": 0.75, "word": "world", "speaker": "A"},
        {"start": 1.50, "end": 1.80, "word": "你好", "speaker": "B"},
        {"start": 1.82, "end": 2.10, "word": "世界", "speaker": "B"},
    ]


def test_join_tokens_handles_cjk_and_punctuation():
    assert join_tokens(["Hello", "world", "!", "你好", "世界", "。"]) == "Hello world!你好世界。"


def test_pack_phrases_breaks_on_silence_and_speaker():
    phrases = pack_phrases(_words(), silence_gap_seconds=0.5)
    assert [phrase["text"] for phrase in phrases] == ["Hello world!".replace("!", ""), "你好世界"]
    assert phrases[0]["speaker"] == "A"
    assert phrases[1]["speaker"] == "B"


def test_editorial_transcript_writes_schema_valid_artifact(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-v1")
    output = tmp_path / "editorial.json"
    result = EditorialTranscript().execute({
        "source_path": str(source),
        "transcript": {"provider": "whisperx", "language": "en", "word_timestamps": _words()},
        "output_path": str(output),
    })
    assert result.success, result.error
    assert output.is_file()
    assert result.data["phrases"][0]["text"] == "Hello world"
    validate_artifact("editorial_transcript", result.data)

    first_fingerprint = result.data["source_fingerprint"]
    source.write_bytes(b"source-v2")
    second = EditorialTranscript().execute({
        "source_path": str(source),
        "transcript": {"provider": "whisperx", "language": "en", "word_timestamps": _words()},
        "output_path": str(output),
    })
    assert second.success
    assert second.data["source_fingerprint"] != first_fingerprint


def test_boundary_issues_report_split_word_and_padding_warning():
    words = [{"start": 0.0, "end": 1.0, "text": "word"}]
    split = boundary_issues(words, 0.5, min_padding_seconds=0.03)
    assert split[0]["code"] == "split_word"
    edge = boundary_issues(words, 1.01, min_padding_seconds=0.03)
    assert edge[0]["code"] == "insufficient_padding"


def test_cut_boundary_qa_checks_every_boundary_and_validates_artifact(tmp_path):
    output = tmp_path / "cut_review.json"
    result = CutBoundaryQA().execute({
        "edit_decisions": {
            "version": "1.0",
            "cuts": [
                {"id": "a", "source": "take.mp4", "in_seconds": 0.0, "out_seconds": 0.5},
                {"id": "b", "source": "take.mp4", "in_seconds": 0.5, "out_seconds": 1.5},
                {"id": "c", "source": "take.mp4", "in_seconds": 1.5, "out_seconds": 2.2},
            ],
            "render_runtime": "ffmpeg",
        },
        "transcript": {"source_id": "take.mp4", "word_timestamps": _words()},
        "generate_evidence": False,
        "output_path": str(output),
    })
    assert not result.success
    assert result.data["summary"]["checked_boundaries"] == 2
    assert result.data["summary"]["coverage_complete"] is True
    assert result.data["status"] == "fail"
    validate_artifact("cut_review", result.data)
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "fail"


def test_edit_timeline_roundtrip_and_revision_conflict():
    timeline = normalize_edit_decisions({
        "version": "1.0",
        "render_runtime": "remotion",
        "cuts": [
            {"id": "a", "source": "one.mp4", "in_seconds": 0, "out_seconds": 2},
            {"id": "b", "source": "two.mp4", "in_seconds": 1, "out_seconds": 4},
        ],
    })
    validate_artifact("edit_timeline", timeline)
    updated = apply_timeline_operations(
        timeline,
        [
            {"op": "trim", "segment_id": "a", "source_in_seconds": 0.25, "source_out_seconds": 1.75},
            {"op": "set_zoom_keyframe", "segment_id": "a", "time_seconds": 0.4, "scale": 1.25, "x": 0.5, "y": 0.4, "easing": "ease-in-out"},
        ],
        expected_revision=0,
    )
    assert updated["revision"] == 1
    assert updated["segments"][0]["source_in_seconds"] == 0.25
    assert updated["segments"][0]["timeline_end_seconds"] == 1.5
    assert len(updated["zoom_keyframes"]) == 1
    with pytest.raises(ValueError, match="revision conflict"):
        apply_timeline_operations(updated, [], expected_revision=0)
