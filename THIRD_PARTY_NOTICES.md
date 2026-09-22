# OpenMontage Video third-party notices

The repository is AGPLv3.  This file records the external runtimes used by
the optional `$openmontage-video` skill; it is not a relicensing notice for
the repository as a whole.

| Component | Pinned version | License / source | Used for |
| --- | --- | --- | --- |
| Node.js | 22.x | Node.js license; https://nodejs.org/ | HyperFrames and Playwright runtime |
| Playwright | 1.62.1 | Apache-2.0; https://www.npmjs.com/package/playwright | Declarative browser capture |
| HyperFrames | 0.7.109 | See upstream notices; https://github.com/heygen-com/hyperframes | Native 3D UI composition |
| librosa | 0.11.0 | ISC; https://librosa.org/ | Beat/onset analysis |
| soundfile | 0.13.1 | BSD-3-Clause; https://python-soundfile.readthedocs.io/ | Audio decoding |
| NumPy | 2.3.5 | BSD-3-Clause; https://numpy.org/ | Numeric analysis |
| Pillow | >=10.0 | HPND / Pillow license; https://pillow.readthedocs.io/ | Timeline evidence compositor and existing graphics tools |
| FFmpeg | 8.x or compatible floor | LGPL/GPL build-dependent; https://ffmpeg.org/legal.html | Media normalization and thumbnails |

The exact npm dependency graph is locked by
`tools/capture/playwright_runtime/package-lock.json` when dependencies are
installed.  Run `python scripts/license_scan.py --check` before release and
regenerate `docs/sbom/openmontage-video.cdx.json` from the lockfiles; do not
copy user media, medical documents, fonts, or third-party music into public
fixtures.

## Reference projects (not vendored)

The following repositories informed feature-level design only. Their source code, assets and
runtime packages are not included in this repository:

| Reference | Upstream license | Boundary for this implementation |
| --- | --- | --- |
| [browser-use/video-use](https://github.com/browser-use/video-use) | MIT | Clean-room implementation of provider-neutral transcripts, timeline inspection and cut QA; no code copied. |
| [CristianOlivera1/openvid](https://github.com/CristianOlivera1/openvid) | PolyForm Noncommercial 1.0.0, source-available | Clean-room implementation of revisioned timeline authoring and Backlot API; no OpenVid code or browser capture runtime vendored. The license is not an OSI open-source license. |

The repository itself remains AGPLv3. Direct integration, redistribution or commercial use of
OpenVid code would require a separate license review; this notice does not grant those rights.
