# Contributing to OpenMontage

Thank you for improving OpenMontage. We do not require a Contributor License Agreement (CLA), Developer Certificate of Origin sign-off, or any separate contribution contract.

By submitting a pull request, you confirm that you have the right to contribute its contents. Contributions must be compatible with the repository's [AGPLv3 license](LICENSE), and accepted contributions remain available under that license.

Please keep pull requests focused and include tests when behavior changes.

## Source-led editing changes

Changes to the footage-led editing layer should keep the data contract and native render path
in sync:

- Update the relevant JSON Schema in `schemas/artifacts/` and the `ARTIFACT_NAMES` catalog when
  adding or changing a canonical artifact.
- Keep `edit_timeline` operations auditable and fail closed for unknown operations; preserve the
  existing `edit_decisions` fields when round-tripping to `video_compose`.
- Add focused tests for tool output, schema validation, revision conflicts and Backlot routes.
- Keep browser/UI authoring separate from rendering. Do not add a second renderer or silently
  downgrade an approved runtime when a keyframe is unsupported.
- Update [`docs/EDIT_TIMELINE.md`](docs/EDIT_TIMELINE.md), the relevant README and
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) when the public contract or dependency/
  licensing boundary changes.
- Do not copy or vendor code/assets from reference projects without a separate license review;
  in particular, OpenVid's PolyForm Noncommercial terms are not inherited from this repository's
  AGPLv3 license.

Before opening a pull request, run the focused editing tests and the pipeline/catalog contract
tests listed in [`docs/EDIT_TIMELINE.md`](docs/EDIT_TIMELINE.md).
