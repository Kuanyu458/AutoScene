"""Fail closed when a prospective public tree contains private/local files.

In CI this inspects ``git ls-files``. Before Git metadata is attached, it can
still audit a working-tree candidate while excluding known local-only paths;
the report explicitly marks that mode so it is never confused with a history
or tracked-tree audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


FORBIDDEN_EXACT = {".env", ".DS_Store"}
FORBIDDEN_PREFIXES = (
    ".venv/",
    "venv/",
    "projects/",
    "remotion-composer/node_modules/",
    "tests/qa/output/",
    ".pytest_cache/",
)
LOCAL_ONLY_PREFIXES = FORBIDDEN_PREFIXES + (
    "dist/",
    "build/",
    "output/",
    "pipeline/",
    "remotion-composer/out/",
    "remotion-composer/projects/",
)
REQUIRED_PUBLIC_FILES = (
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
)
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{30,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "mac_user_path": re.compile("/" + "Users" + r"/[^/\s]+/"),
    "linux_user_path": re.compile("/" + "home" + r"/[^/\s]+/"),
    "windows_user_path": re.compile(
        r"[A-Za-z]:[\\/]" + "Users" + r"[\\/][^\\/\s]+[\\/]"
    ),
}
APPROVED_LARGE_FILES = {
    ".agents/skills/hyperframes-animation/examples/assets/hyperframes-showcase-hypecard.mp4":
        "59894d108c5634cce855f4b9593d48ee0884955b1607e0f1c1c4e973e2eb101e",
    ".agents/skills/hyperframes-animation/examples/assets/background-tech-data-flow.mp4":
        "f5d7c64dffda80b3b15bd116e4f2fda2231ae5d7997f2753ba01051aa243ce79",
    "assets/signal-from-tomorrow-demo.mp4":
        "47d46d729e0881d37ea87e49a0d1cfb8277434bb58d66e0d51ac5163fd020dac",
}


def _git_files(root: Path) -> list[str] | None:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item]


def _is_local_only(relative: str) -> bool:
    if relative in FORBIDDEN_EXACT:
        return True
    return any(relative.startswith(prefix) for prefix in LOCAL_ONLY_PREFIXES)


def _candidate_files(root: Path) -> list[str]:
    files: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/") or _is_local_only(relative):
            continue
        if (
            "__pycache__" in path.parts
            or any(part.endswith(".egg-info") for part in path.parts)
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        files.append(relative)
    return sorted(files)


def scan_public_paths(root: Path, paths: Iterable[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in sorted(set(paths)):
        if relative in FORBIDDEN_EXACT or any(relative.startswith(p) for p in FORBIDDEN_PREFIXES):
            findings.append({"code": "FORBIDDEN_PATH", "path": relative})
            continue
        if "__pycache__" in Path(relative).parts or relative.endswith((".pyc", ".pyo")):
            findings.append({"code": "GENERATED_PYTHON", "path": relative})
            continue
        if any(part.endswith(".egg-info") for part in Path(relative).parts):
            findings.append({"code": "GENERATED_PACKAGE", "path": relative})
            continue
        path = root / relative
        if not path.is_file():
            continue
        if path.stat().st_size > 10 * 1024 * 1024:
            approved_hash = APPROVED_LARGE_FILES.get(relative)
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_hash != approved_hash:
                findings.append({"code": "UNAPPROVED_LARGE_FILE", "path": relative})
                continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for code, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"code": code.upper(), "path": relative})
    return findings


def audit(root: Path) -> dict[str, object]:
    tracked = _git_files(root)
    mode = "git-tracked" if tracked is not None else "working-tree-candidate"
    paths = tracked if tracked is not None else _candidate_files(root)
    findings = scan_public_paths(root, paths)
    missing = [relative for relative in REQUIRED_PUBLIC_FILES if not (root / relative).is_file()]
    findings.extend({"code": "REQUIRED_FILE_MISSING", "path": relative} for relative in missing)
    return {
        "schema": "OpenMontagePublicTreeAudit@1.0",
        "mode": mode,
        "ready": not findings,
        "files_checked": len(paths),
        "findings": findings,
        "warnings": (
            ["No Git metadata: history, remote identity, and previously committed secrets were not audited."]
            if tracked is None
            else []
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit(Path(args.root).resolve())
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Public tree: {'READY' if report['ready'] else 'BLOCKED'} ({report['mode']})")
        print(f"Files checked: {report['files_checked']}")
        for finding in report["findings"]:
            print(f"  FAIL {finding['code']}: {finding['path']}")
        for warning in report["warnings"]:
            print(f"  WARN {warning}")
    return 0 if report["ready"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
