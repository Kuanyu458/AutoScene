"""Cross-platform, source-checkout bootstrap for AutoScene.

The script creates an isolated Python environment, installs this checkout in
editable mode, installs the lockfile-pinned Remotion workspace with ``npm ci``,
and runs the public doctor. It never installs system packages or overwrites an
existing ``.env``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


MIN_PYTHON = (3, 12)
MIN_NODE_MAJOR = 22


def _venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(command: list[str], *, cwd: Path, dry_run: bool) -> None:
    print("+ " + " ".join(command))
    if not dry_run:
        subprocess.run(command, cwd=cwd, check=True)


def _version(command: str, *args: str) -> str | None:
    path = shutil.which(command)
    if not path:
        return None
    result = subprocess.run([path, *args], capture_output=True, text=True, check=False)
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if result.returncode == 0 and text else None


def _node_major(version: str | None) -> int | None:
    if not version:
        return None
    text = version.lstrip("v")
    try:
        return int(text.split(".", 1)[0])
    except ValueError:
        return None


def _system_prerequisites() -> tuple[dict[str, str | None], list[str]]:
    versions = {
        "ffmpeg": _version("ffmpeg", "-version"),
        "ffprobe": _version("ffprobe", "-version"),
        "node": _version("node", "--version"),
        "npm": _version("npm", "--version"),
    }
    missing = [name for name in ("ffmpeg", "ffprobe", "node", "npm") if not versions[name]]
    node_major = _node_major(versions["node"])
    if node_major is not None and node_major < MIN_NODE_MAJOR:
        missing.append(f"node>={MIN_NODE_MAJOR}")
    return versions, missing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", default=".venv", help="virtualenv path relative to checkout")
    parser.add_argument("--dev", action="store_true", help="also install test dependencies")
    parser.add_argument("--dry-run", action="store_true", help="print planned operations without writing")
    parser.add_argument("--skip-doctor", action="store_true", help="skip final runtime diagnosis")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if sys.version_info[:2] < MIN_PYTHON:
        print("Python 3.12 or newer is required.", file=sys.stderr)
        return 3

    versions, missing = _system_prerequisites()
    print(json.dumps({"system_dependencies": versions}, indent=2))
    if missing and not args.dry_run:
        print(
            "Missing system prerequisites: " + ", ".join(missing) + ". "
            "Install them using docs/INSTALLATION.md, then rerun this command.",
            file=sys.stderr,
        )
        return 3

    environment = (root / args.venv).resolve()
    python = _venv_python(environment)
    if args.dry_run:
        print(f"+ create virtualenv {environment}")
    elif not python.is_file():
        print(f"==> Creating virtualenv: {environment}")
        venv.EnvBuilder(with_pip=True).create(environment)
    else:
        print(f"==> Reusing virtualenv: {environment}")

    install_target = ".[dev]" if args.dev else "."
    _run([str(python), "-m", "pip", "install", "-e", install_target], cwd=root, dry_run=args.dry_run)
    _run(
        [
            shutil.which("npm") or "npm",
            "ci",
            "--no-audit",
            "--no-fund",
            "--cache",
            str(environment / ".npm-cache"),
        ],
        cwd=root / "remotion-composer",
        dry_run=args.dry_run,
    )

    env_path = root / ".env"
    if args.dry_run:
        print(f"+ create {env_path} from .env.example only if absent")
    elif not env_path.exists():
        shutil.copy2(root / ".env.example", env_path)
        print("==> Created .env from .env.example (all API keys remain optional).")
    else:
        print("==> Existing .env preserved.")

    if not args.skip_doctor:
        _run([str(python), "-m", "openmontage", "doctor"], cwd=root, dry_run=args.dry_run)
    print("\nSetup complete." if not args.dry_run else "\nDry run complete; no files were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
