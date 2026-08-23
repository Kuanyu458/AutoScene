import subprocess
import tomllib
from pathlib import Path

from scripts import bootstrap
from scripts.check_public_tree import scan_public_paths


ROOT = Path(__file__).resolve().parents[2]


def test_distribution_declares_the_reproducible_runtime_floor():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["requires-python"] == ">=3.12"
    assert "librosa==1.0.0" in project["dependencies"]
    assert "soundfile==0.14.0" in project["dependencies"]
    assert project["scripts"]["openmontage"] == "openmontage.cli:main"


def test_bootstrap_uses_each_tools_real_version_flag(monkeypatch):
    calls: list[list[str]] = []
    versions = {
        "ffmpeg": "ffmpeg version 7.1",
        "ffprobe": "ffprobe version 7.1",
        "node": "v22.22.0",
        "npm": "10.9.0",
    }

    monkeypatch.setattr(bootstrap.shutil, "which", lambda command: f"/tools/{command}")

    def fake_run(command, **_kwargs):
        calls.append(command)
        name = Path(command[0]).name
        return subprocess.CompletedProcess(command, 0, stdout=versions[name] + "\n", stderr="")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    _reported, missing = bootstrap._system_prerequisites()

    assert missing == []
    assert ["/tools/ffmpeg", "-version"] in calls
    assert ["/tools/ffprobe", "-version"] in calls
    assert ["/tools/node", "--version"] in calls
    assert ["/tools/npm", "--version"] in calls


def test_bootstrap_dry_run_isolated_npm_cache(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        bootstrap,
        "_system_prerequisites",
        lambda: ({"ffmpeg": "ok", "ffprobe": "ok", "node": "v22", "npm": "10"}, []),
    )

    exit_code = bootstrap.main(["--dry-run", "--venv", str(tmp_path / "venv")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert str(tmp_path / "venv" / ".npm-cache") in output


def test_public_tree_gate_rejects_private_and_unreviewed_content(tmp_path: Path):
    secret = tmp_path / "secret.txt"
    secret.write_text("ghp_" + "A" * 32, encoding="utf-8")
    personal = tmp_path / "personal.md"
    personal.write_text("/" + "Users" + "/alice/private/video.mov", encoding="utf-8")
    egg_info = tmp_path / "local.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("generated", encoding="utf-8")
    large = tmp_path / "large.bin"
    with large.open("wb") as handle:
        handle.seek(10 * 1024 * 1024)
        handle.write(b"x")

    findings = scan_public_paths(
        tmp_path,
        [".env", "secret.txt", "personal.md", "local.egg-info/PKG-INFO", "large.bin"],
    )
    codes = {item["code"] for item in findings}

    assert codes == {
        "FORBIDDEN_PATH",
        "GITHUB_TOKEN",
        "GENERATED_PACKAGE",
        "MAC_USER_PATH",
        "UNAPPROVED_LARGE_FILE",
    }


def test_ci_covers_python_node_windows_and_trusted_macos():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    macos = (ROOT / ".github/workflows/macos-arm64-e2e.yml").read_text(encoding="utf-8")

    assert 'python-version: ["3.12", "3.13"]' in ci
    assert 'node-version: "22"' in ci
    assert "npm ci --prefix remotion-composer" in ci
    assert "npm run typecheck --prefix remotion-composer" in ci
    assert "runs-on: windows-latest" in ci
    assert "runs-on: [self-hosted, macOS, ARM64]" in macos
    assert 'OPENMONTAGE_MACOS_E2E: "1"' in macos
