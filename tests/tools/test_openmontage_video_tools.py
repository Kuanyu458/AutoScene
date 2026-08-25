"""Unit-level tests that do not require a browser or a HyperFrames install."""

from tools.audio.audio_timing import AudioTiming
from tools.capture.playwright_recorder import PlaywrightRecorder


def test_audio_timing_snaps_unlocked_and_preserves_semantic_lock():
    tool = AudioTiming()
    result = tool.execute(
        {
            "operation": "snap_markers",
            "audiomap": {
                "version": "1.0",
                "status": "applied",
                "grid": {"beats_sec": [1.0, 2.0, 3.0], "downbeats_sec": [1.0, 3.0]},
            },
            "markers": [
                {"id": "semantic", "nominal_seconds": 1.08, "semantic_locked": True},
                {"id": "snap", "nominal_seconds": 2.08, "semantic_locked": False},
            ],
            "snap_tolerance_ms": 250,
        }
    )
    assert result.success
    assert result.data["markers"][0]["applied_seconds"] == 1.08
    assert result.data["markers"][1]["applied_seconds"] == 2.0
    assert result.data["max_abs_delta_seconds"] == 0.08


def test_audio_timing_rejects_marker_outside_tolerance():
    result = AudioTiming().execute(
        {
            "operation": "snap_markers",
            "audiomap": {"version": "1.0", "status": "applied", "grid": {"beats_sec": [1.0]}},
            "markers": [{"nominal_seconds": 2.0}],
            "snap_tolerance_ms": 250,
        }
    )
    assert not result.success
    assert "exceeds" in (result.error or "")


def test_playwright_recorder_preflight_blocks_credentials_and_cross_origin():
    tool = PlaywrightRecorder()
    safe = {
        "operation": "preflight",
        "base_url": "http://127.0.0.1:8000",
        "flows": [{"name": "demo", "steps": [{"op": "goto", "url": "/"}, {"op": "click", "selector": "#start"}]}],
    }
    safe_result = tool.execute(safe)
    assert safe_result.success
    assert safe_result.data["base_origin"] == "http://127.0.0.1:8000"
    blocked_secret = tool.execute({**safe, "flows": [{"name": "demo", "steps": [{"op": "fill", "selector": "#password", "value": "secret"}]}]})
    assert not blocked_secret.success
    assert "credential" in (blocked_secret.error or "")
    blocked_origin = tool.execute({**safe, "flows": [{"name": "demo", "steps": [{"op": "goto", "url": "https://example.com"}]}]})
    assert not blocked_origin.success
    assert "origin" in (blocked_origin.error or "")
    blocked_script = tool.execute({**safe, "flows": [{"name": "demo", "steps": [{"op": "wait", "seconds": 0, "script": "alert(1)"}]}]})
    assert not blocked_script.success
    assert "blocked fields" in (blocked_script.error or "")
