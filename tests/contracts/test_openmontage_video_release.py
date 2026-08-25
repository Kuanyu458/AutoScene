"""Release metadata checks for the openmontage-video addition."""

import json
from pathlib import Path

from scripts.license_scan import build_sbom


ROOT = Path(__file__).resolve().parents[2]


def test_lockfiles_and_sbom_are_pinned_and_known():
    sbom = build_sbom()
    names = {component["name"] for component in sbom["components"]}
    assert {"playwright", "playwright-core", "librosa", "soundfile", "numpy"} <= names
    lock = json.loads((ROOT / "tools/capture/playwright_runtime/package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"]["node_modules/playwright"]["version"] == "1.62.1"
    assert lock["packages"]["node_modules/playwright-core"]["version"] == "1.62.1"
    checked_in = json.loads((ROOT / "docs/sbom/openmontage-video.cdx.json").read_text(encoding="utf-8"))
    assert checked_in["bomFormat"] == "CycloneDX"
    assert {component["name"] for component in checked_in["components"]} == names
