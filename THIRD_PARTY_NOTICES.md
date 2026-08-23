# Third-party notices

This file records material licensing boundaries for the Beat3D distribution.
It is not legal advice. Versions refer to the lockfiles in this repository.

## Parent project

- **OpenMontage** — upstream source:
  <https://github.com/calesthio/OpenMontage>
- **License:** GNU Affero General Public License v3, retained in [`LICENSE`](LICENSE).
- Beat3D is a derivative distribution; the repository license does not
  relicense dependencies, user media, models, fonts, music, or generated output.

## Default 3D/render stack

| Dependency | Locked version | Terms | Source |
|---|---:|---|---|
| Remotion / `@remotion/*` | 4.0.484 | Remotion License, not MIT/AGPL | <https://github.com/remotion-dev/remotion/blob/main/LICENSE.md> |
| Three.js | 0.155.0 | MIT | <https://github.com/mrdoob/three.js/blob/dev/LICENSE> |
| React Three Fiber | 8.18.0 | MIT | <https://github.com/pmndrs/react-three-fiber/blob/master/LICENSE> |
| FFmpeg / ffprobe | system install | LGPL/GPL configuration-dependent | <https://ffmpeg.org/legal.html> |

The Remotion license in effect at verification time allows free use by
individuals, nonprofits, evaluation users, and for-profit organizations up to
the stated employee threshold; other for-profit organizations may require a
company license. Read the current official license before commercial use. This
repository does not bundle or grant a Remotion commercial license.

The composer pins reviewed security overrides for three Remotion bundler
transitive packages. See [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md);
these overrides do not alter or replace any dependency's license.

## Python runtime

Python packages are installed from PyPI through `pyproject.toml`; they are not
vendored. Their own distributions include authoritative license notices.
Material packages include PyYAML, Pydantic, jsonschema, python-dotenv, Pillow,
NumPy, Requests, librosa, SoundFile, google-auth, google-genai, openai, FastAPI,
Uvicorn, watchfiles, and the development-only httpx dependency.

## Layer-3 knowledge packs and assets

The inherited `.agents/skills/` tree contains upstream and third-party
knowledge packs. Some subtrees contain separate provenance or license text;
some include GSAP examples or other material whose terms are not the root
AGPL. Do not claim that every file in that tree is AGPL.

For a public release, prefer a real upstream fork so unchanged inherited files
retain their history. Any newly added vendored material must include its source,
version/commit, and redistribution terms in
[`docs/ASSET_PROVENANCE.md`](docs/ASSET_PROVENANCE.md). Files without a verified
redistribution basis must be removed from the release or fetched by the user at
install time.

The following vendored HyperFrames skill directories come from
[`heygen-com/hyperframes`](https://github.com/heygen-com/hyperframes) commit
`3351fb1a` / tag `v0.7.17`: `hyperframes`, `hyperframes-cli`,
`hyperframes-registry`, `hyperframes-core`, `hyperframes-creative`,
`hyperframes-media`, `hyperframes-animation`, `media-use`, `motion-graphics`,
`remotion-to-hyperframes`, `music-to-video`, and `website-to-video`. They are
distributed under Apache License 2.0; the complete upstream LICENSE text is
retained in
[`LICENSES/HyperFrames-Apache-2.0.txt`](LICENSES/HyperFrames-Apache-2.0.txt),
with detailed file provenance in
[`.agents/skills/hyperframes/PROVENANCE.md`](.agents/skills/hyperframes/PROVENANCE.md).

## CutClaw boundary

The Beat3D implementation references the public CutClaw paper and repository
only as methodology:

- repository snapshot: <https://github.com/GVCLab/CutClaw/commit/db48d08b0d48881df0dda0b207b6873148c88077>
- paper: <https://arxiv.org/abs/2603.29664>

No CutClaw code, package, submodule, CLI, renderer, or runtime import is
distributed or executed. GitHub's repository-license endpoint returned no
license file during the 2026-08-24 release audit, so independent implementation
is an explicit boundary rather than an implied permission to copy its code.

## Recordly external-app boundary

[Recordly](https://github.com/webadderallorg/Recordly) is an optional external
desktop recorder for the `screen-demo` real-capture path. The integration was
reviewed against commit
[`72e9724505e2498fd85754cfe69e02d8a69900a0`](https://github.com/webadderallorg/Recordly/commit/72e9724505e2498fd85754cfe69e02d8a69900a0).

Recordly is distributed by its authors under GNU AGPLv3 with additional
project-specific attribution and branding guidance in its license file. Users
install and operate it separately under those terms. OpenMontage does not
vendor, fork, bundle, import, or redistribute Recordly code or assets, and it
does not use the Recordly name or artwork as OpenMontage branding. This project
is not affiliated with or endorsed by Recordly.

The adapter only detects a local installation, opens it on an explicit request,
and imports an explicitly selected exported MP4 as user content. It does not
depend on Recordly's undocumented smoke-test export variables or treat a
`.recordly` project as a portable bundle. User recordings and Recordly project
files remain user content and are not relicensed by this repository.

## User content

Files under `projects/`, `music_library/`, local model caches, `.env`, and
render outputs are excluded from the public tree. Users are responsible for
the rights to source footage, images, music, fonts, models, and final output.
