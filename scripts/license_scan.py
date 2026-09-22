#!/usr/bin/env python3
"""Offline license/SBOM check for the openmontage-video lockfiles.

The scanner intentionally uses the checked-in manifests rather than reaching
out to package registries.  Release CI can run a richer scanner after
installation; this check catches drift, unpinned dependencies, and unknown
declared licenses before a release is assembled.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tools" / "capture" / "playwright_runtime"
KNOWN = {
    "playwright": "Apache-2.0",
    "playwright-core": "Apache-2.0",
    "fsevents": "MIT",
    "librosa": "ISC",
    "soundfile": "BSD-3-Clause",
    "numpy": "BSD-3-Clause",
    "node": "Node.js license",
    "hyperframes": "upstream-notice-required",
    "ffmpeg": "LGPL/GPL build-dependent",
}


def _python_requirements() -> list[dict[str, str]]:
    path = ROOT / "requirements-openmontage-video.txt"
    components: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise ValueError(f"unlocked or malformed Python requirement: {line}")
        name, version = match.groups()
        key = name.lower()
        if key not in KNOWN:
            raise ValueError(f"no license mapping for Python dependency: {name}")
        components.append({"name": name, "version": version, "license": KNOWN[key], "type": "library"})
    return components


def _npm_components() -> list[dict[str, str]]:
    path = RUNTIME / "package-lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    components: list[dict[str, str]] = []
    for package_path, info in packages.items():
        if not package_path.startswith("node_modules/"):
            continue
        name = package_path.split("node_modules/", 1)[1]
        if name.startswith("@") and "/" in name:
            # Keep scoped package names intact; the current runtime has none.
            name = name
        version = str(info.get("version", ""))
        if not version:
            raise ValueError(f"npm lock entry has no version: {package_path}")
        if name.lower() not in KNOWN:
            raise ValueError(f"no license mapping for npm dependency: {name}")
        components.append({"name": name, "version": version, "license": KNOWN[name.lower()], "type": "library"})
    return components


def build_sbom() -> dict[str, Any]:
    components = _python_requirements() + _npm_components()
    components.extend(
        {"name": name, "version": version, "license": KNOWN[name], "type": "framework"}
        for name, version in (("node", "22.x"), ("hyperframes", "0.7.109"), ("ffmpeg", "8.x floor"))
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "openmontage-video", "version": "1.0"}},
        "components": sorted(components, key=lambda item: (item["type"], item["name"].lower())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, help="Write a CycloneDX JSON SBOM")
    parser.add_argument("--check", action="store_true", help="Only validate lockfiles and known licenses")
    args = parser.parse_args(argv)
    try:
        sbom = build_sbom()
        if args.write:
            args.write.parent.mkdir(parents=True, exist_ok=True)
            args.write.write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not args.write or args.check:
            print(json.dumps({"valid": True, "component_count": len(sbom["components"])}, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
