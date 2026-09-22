"""Short localhost smoke test for the optional Playwright backend."""

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

from tools.capture.playwright_recorder import PlaywrightRecorder


@pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_VIDEO_E2E") != "1",
    reason="set OPENMONTAGE_VIDEO_E2E=1 after installing Playwright Chromium",
)
def test_localhost_recording_smoke(tmp_path):
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "openmontage_video_demo"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(fixture_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "capture.mp4"
        result = PlaywrightRecorder().execute(
            {
                "operation": "record",
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "flows": [{
                    "name": "fixture",
                    "steps": [
                        {"op": "goto", "url": "/"},
                        {"op": "click", "selector": "#go"},
                        {"op": "assert", "selector": "#result", "expected": "Result ready"},
                        {"op": "screenshot", "selector": "#result", "path": "result.png"},
                    ],
                }],
                "output_path": str(output),
                "slow_mo": 0,
                "timeout_seconds": 90,
            }
        )
        assert result.success, result.error
        assert output.is_file()
        assert Path(result.data["webm_path"]).is_file()
        assert Path(result.data["privacy_report_path"]).is_file()
        assert result.data["interaction_events"]
    finally:
        server.shutdown()
        server.server_close()
