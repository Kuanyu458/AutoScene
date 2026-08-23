from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_cutclaw_is_not_a_dependency_or_production_import():
    dependency_files = [
        ROOT / "requirements.txt",
        ROOT / "requirements-dev.txt",
        ROOT / "setup.py",
        ROOT / "remotion-composer" / "package.json",
    ]
    for path in dependency_files:
        assert "cutclaw" not in path.read_text(encoding="utf-8").lower(), path

    production_files = [
        *ROOT.glob("lib/**/*.py"),
        *ROOT.glob("tools/**/*.py"),
        *ROOT.glob("remotion-composer/src/**/*.*"),
    ]
    for path in production_files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        assert "import cutclaw" not in text
        assert "from cutclaw" not in text
