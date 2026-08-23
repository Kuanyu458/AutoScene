# Contributing to AutoScene

AutoScene is an independent derivative of OpenMontage. It keeps the upstream
agent-first architecture: Python contains
tools and persistence, while pipeline decisions live in manifests and director
skills. Do not add a Python creative orchestrator.

We do not require a Contributor License Agreement (CLA), Developer Certificate
of Origin sign-off, or any separate contribution contract. By submitting a pull
request, you confirm that you have the right to contribute its contents.
New AutoScene-owned source contributions must be compatible with the
repository's [AGPLv3 license](LICENSE), and accepted contributions remain
available under that license. Inherited or separately licensed third-party
components retain the terms identified in their own license and provenance
files; see `THIRD_PARTY_NOTICES.md`.

## Development setup

```bash
python3 scripts/bootstrap.py --dev
.venv/bin/python -m pytest -q
cd remotion-composer && npm run typecheck
```

Before changing a tool or pipeline, read `AGENT_GUIDE.md` and
`PROJECT_CONTEXT.md`.

## Pull requests

- Keep one logical concern per PR.
- Add or update contract tests at the public interface.
- Preserve frame-authoritative TimelineV2 semantics.
- Keep deterministic 3D frame-driven; no wall clock, `useFrame()`, remote asset,
  or silent runtime fallback.
- Never add user media, `.env`, models, render output, or unlicensed assets.
- Add provenance and third-party terms for any vendored material.
- Run `make verify-release PYTHON=.venv/bin/python`.

Changes based on an external method must cite it and identify whether code was
copied. An absent or unclear external license means no code is copied or
vendored.
