from lib.pipeline_loader import get_stage_order, list_pipelines, load_pipeline


def test_every_pipeline_manifest_loads_against_catalog_schema():
    failures = {}
    for name in sorted(list_pipelines()):
        try:
            load_pipeline(name)
        except Exception as exc:  # pragma: no cover - assertion formats the catalog
            failures[name] = f"{type(exc).__name__}: {exc}"
    assert not failures


def test_auto_montage_uses_only_canonical_checkpoint_stages():
    manifest = load_pipeline("auto-montage-3d")
    assert manifest["stability"] == "beta"
    assert get_stage_order(manifest) == [
        "research", "proposal", "scene_plan", "assets", "edit", "compose", "publish"
    ]
