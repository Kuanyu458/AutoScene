from tools.analysis.cut_boundary_qa import CutBoundaryQA


def test_cut_review_marks_missing_evidence_source_as_needs_review(tmp_path):
    result = CutBoundaryQA().execute({
        "edit_decisions": {
            "version": "1.0",
            "cuts": [
                {"id": "a", "source": "take.mp4", "in_seconds": 0, "out_seconds": 1},
                {"id": "b", "source": "take.mp4", "in_seconds": 1, "out_seconds": 2},
            ],
        },
        "transcript": {"source_id": "take.mp4", "word_timestamps": [
            {"start": 0.1, "end": 0.3, "word": "ok"},
        ]},
        "output_path": str(tmp_path / "review.json"),
    })
    assert result.success
    assert result.data["status"] == "needs_review"
    assert result.data["summary"]["warning_count"] == 1
    assert result.data["boundaries"][0]["evidence_error"]
