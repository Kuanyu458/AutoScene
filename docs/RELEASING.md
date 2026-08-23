# Release checklist

AutoScene is published from the GitHub fork at
<https://github.com/Kuanyu458/AutoScene>. The release branch preserves the
upstream OpenMontage history and records both the reconstructed source-delta
base and the newer integration target in `UPSTREAM.md`.

1. Fetch both `origin` and <https://github.com/calesthio/OpenMontage> as
   `upstream` and confirm the intended integration target.
2. Create `codex/autoscene-beat3d-recordly` from the fork's current `main`.
3. Apply the reviewed Beat3D/Recordly delta; do not copy `.env`, `.venv`, `node_modules`,
   `projects`, QA output, caches, or local renders.
4. Record source-delta base `80e51fd6181736e856a138eaac1cbbb36dac54ab`
   and integration target `cd9f3c1f03368be87b140af494914b8ee4e3c7a4`
   in the release PR and `UPSTREAM.md`.
5. Review `THIRD_PARTY_NOTICES.md`, `docs/ASSET_PROVENANCE.md`, and refresh
   `docs/VERIFICATION.md` with evidence from the release candidate.
6. Run:

   ```bash
   python3 scripts/bootstrap.py --dev
   .venv/bin/python scripts/check_public_tree.py
   .venv/bin/python -m pytest -q
   cd remotion-composer && npm run typecheck
   npm audit --omit=dev --audit-level=high
   ```

7. Run the macOS live E2E on Apple Silicon.
8. Inspect `git status --short`, `git diff --check`, the full tracked tree, and
   repository history with a secret scanner.
9. Open a draft PR and let the GitHub Actions matrix pass.
10. Tag `v0.2.0-beta.1` only after license notices, source provenance, and CI
    are clean.

Do not claim a GitHub release, remote branch, PR, or published tag until its
live state has been queried and the commit is confirmed attached to it.
