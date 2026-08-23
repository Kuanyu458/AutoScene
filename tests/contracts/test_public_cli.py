import hashlib
import json
import subprocess
import sys
from pathlib import Path

from openmontage.cli import doctor_report, main


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_module_entrypoint_reports_version():
    result = subprocess.run(
        [sys.executable, "-m", "openmontage", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "openmontage 0.2.0b1"


def test_doctor_report_is_structured_and_never_echoes_api_keys(monkeypatch):
    marker = "must-not-appear-in-doctor-output"
    monkeypatch.setenv("OPENAI_API_KEY", marker)

    report = doctor_report(ROOT)

    assert report["schema"] == "OpenMontageDoctor@1.0"
    assert report["checks"]["auto_montage_pipeline"]["name"] == "auto-montage-3d"
    assert report["checks"]["recordly_capture"]["optional"] is True
    assert report["checks"]["recordly_capture"]["ingest_ready"] in {True, False}
    assert "recordly_capture" not in report["blockers"]
    assert marker not in json.dumps(report, sort_keys=True)


def test_init_cli_creates_fresh_hash_verified_job(tmp_path: Path, capsys):
    source = tmp_path / "input"
    source.mkdir()
    files = {
        "brief.md": b"A portable beat montage",
        "music.wav": b"RIFF-fake-audio",
        "clip.mp4": b"fake-video",
    }
    for name, content in files.items():
        (source / name).write_bytes(content)
    before = {name: _sha256(source / name) for name in files}

    exit_code = main([
        "init",
        str(source),
        "--projects-root",
        str(tmp_path / "projects"),
        "--slug",
        "portable-demo",
        "--json",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["output"]["request_relative_path"] == "montage_request.json"
    project = Path(payload["output"]["project_dir"])
    assert (project / "montage_request.json").is_file()
    assert all(_sha256(source / name) == digest for name, digest in before.items())
    for record in (payload["brief"], payload["music"], *payload["media"]):
        assert (project / record["staged_relative_path"]).is_file()
