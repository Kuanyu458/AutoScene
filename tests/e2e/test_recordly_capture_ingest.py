import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.artifacts import validate_artifact  # noqa: E402
from tools.capture.recordly_recorder import (  # noqa: E402
    PACKAGE_FILENAME,
    RecordlyRecorder,
)


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="real media ingest requires ffmpeg and ffprobe",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recordly_export_ingest_is_real_media_portable_and_privacy_gated(tmp_path: Path):
    source = tmp_path / "recordly-export.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    source_hash = _sha256(source)
    package_dir = tmp_path / "portable-capture"
    tool = RecordlyRecorder()

    ingested = tool.execute(
        {
            "operation": "ingest",
            "input_path": str(source),
            "output_dir": str(package_dir),
        }
    )

    assert ingested.success, ingested.error
    assert ingested.data["ready_for_pipeline"] is True
    assert ingested.data["ready_for_publish"] is False
    assert _sha256(source) == source_hash

    package_path = package_dir / PACKAGE_FILENAME
    package = json.loads(package_path.read_text(encoding="utf-8"))
    validate_artifact("screen_capture_package", package)
    serialized = package_path.read_text(encoding="utf-8")
    assert str(source) not in serialized
    assert str(package_dir) not in serialized
    assert package["video"]["width"] == 320
    assert package["video"]["height"] == 180
    assert package["video"]["fps"] == 30
    assert package["video"]["has_audio"] is True
    assert package["video"]["sha256"] == source_hash

    pending = tool.execute({"operation": "verify", "output_dir": str(package_dir)})
    assert pending.success, pending.error
    assert pending.data["ready_for_pipeline"] is True
    assert pending.data["ready_for_publish"] is False

    package["privacy_review"] = {
        "status": "passed",
        "reviewed": True,
        "passed": True,
        "sensitive_regions": [],
        "unresolved_count": 0,
        "redactions_verified": True,
    }
    validate_artifact("screen_capture_package", package)
    package_path.write_text(
        json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    approved = tool.execute({"operation": "verify", "output_dir": str(package_dir)})
    assert approved.success, approved.error
    assert approved.data["ready_for_pipeline"] is True
    assert approved.data["ready_for_publish"] is True
