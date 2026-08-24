from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = "72e9724505e2498fd85754cfe69e02d8a69900a0"


def test_recordly_is_an_external_optional_app_not_a_dependency():
    dependency_files = [
        ROOT / "pyproject.toml",
        ROOT / "requirements.txt",
        ROOT / "requirements-dev.txt",
        ROOT / "remotion-composer" / "package.json",
        ROOT / "remotion-composer" / "package-lock.json",
    ]
    for path in dependency_files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        assert '"recordly"' not in text, path
        assert "recordly.git" not in text, path

    assert not (ROOT / "vendor" / "Recordly").exists()
    assert not (ROOT / "third_party" / "Recordly").exists()


def test_recordly_adapter_does_not_depend_on_private_smoke_or_install_contracts():
    adapter = (ROOT / "tools" / "capture" / "recordly_recorder.py").read_text(
        encoding="utf-8"
    )
    lowered = adapter.lower()

    assert "recordly_smoke_export" not in lowered
    assert "recordly_dev_open_recording_input" not in lowered
    assert "npm install" not in lowered
    assert "git clone" not in lowered
    assert "curl " not in lowered


def test_recordly_attribution_and_reviewed_snapshot_are_publicly_documented():
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "RECORDLY_UI_CAPTURE.md").read_text(encoding="utf-8")

    assert UPSTREAM_COMMIT in notice
    assert UPSTREAM_COMMIT in guide
    assert "does not vendor" in guide
    assert "not affiliated with or endorsed by" in notice
    assert ".recordly" in guide
    assert "absolute path" in guide
