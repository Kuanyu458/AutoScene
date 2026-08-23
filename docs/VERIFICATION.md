# OpenMontage Beat3D beta verification record

Verification date: 2026-08-24

This record distinguishes local runtime evidence from GitHub publication and
cross-platform claims. It is evidence for a source-checkout release candidate,
not evidence that a remote repository, branch, pull request, tag, or GitHub
Actions run exists.

## Verified environment

| Component | Verified value |
|---|---|
| Host | macOS, Apple Silicon (`arm64`) |
| Python | 3.13.5 in the bootstrap-managed `.venv` |
| Node.js / npm | 22.22.3 / 10.9.8 |
| FFmpeg / ffprobe | 4.3.2 |
| Remotion family | 4.0.484 |
| `@remotion/three` | 4.0.484 |
| Three.js | 0.155.0 |
| React Three Fiber | 8.18.0 |

## Gates passed

- bootstrap completed with its virtualenv-local npm cache;
- `openmontage doctor` returned `READY` with no blockers;
- `pip check` found no broken requirements;
- complete Python regression: 438 passed, 10 intentionally skipped;
- TypeScript compiler: zero errors;
- Remotion enumerated 14 compositions, including the 1920x1080, 30 fps,
  60-frame `ProceduralThree` smoke composition;
- `npm audit --omit=dev --audit-level=high`: zero vulnerabilities after the
  reviewed exact transitive overrides in `docs/SECURITY_AUDIT.md`;
- public-tree candidate: 1,917 files inspected, zero findings;
- all GitHub workflow YAML parsed successfully.

## Real macOS workflow evidence

The opt-in Apple Silicon E2E generated synthetic source clips and a local 120
BPM click track, analyzed the music, rendered a deterministic procedural 3D
MP4 with ANGLE, planned the frame-authoritative timeline, and composed the
final video.

The test verified:

- source hashes unchanged before and after the run;
- one or more source-video segments plus a procedural 3D segment;
- final 1920x1080, 30 fps H.264 video with AAC audio;
- final duration within one frame;
- planner median cut-to-anchor error at most one frame;
- rendered boundary errors and p95 at most two frames;
- audio/video start drift at most 100 ms;
- non-black 3D preview samples and schema-valid artifacts.

Result: 1 passed.

## Recordly bridge evidence

The optional Recordly bridge was tested without installing or automating the
external desktop app. A real H.264/AAC MP4 was generated locally, ingested from
an explicit path, copied without changing its source hash, probed with ffprobe,
and written as a schema-valid portable `ScreenCapturePackage@1.0`. The test then
moved/verified the package, exercised its pending-to-passed privacy boundary,
and confirmed publish readiness remained false until a complete review existed.

Additional contract tests cover macOS/Windows/Linux install-path detection,
missing dependencies, no-overwrite behavior, failed-copy cleanup, path
traversal, hash tampering, ffprobe/package metadata drift, provenance drift,
selector routing, and the screen-demo publish privacy gate.

Local doctor result:

- Recordly desktop app: not detected;
- adapter status: `degraded` (new local Recordly capture unavailable);
- explicit exported-MP4 ingestion: ready because ffprobe is available;
- default capture recommendation: FFmpeg, preserving existing behavior.

## Explicitly not yet verified

- The current workspace arrived without `.git`; repository history, a remote,
  previously committed secrets, and an exact upstream base commit were not
  available for audit.
- Ubuntu and Windows workflows are authored contract gates but have not run on
  GitHub Actions from this workspace.
- Linux and Windows live WebGL render parity is not claimed.
- HyperFrames remains optional and unavailable for live parity; the accepted
  beta E2E renderer is Remotion.
- A live Recordly GUI recording/export was not performed because the optional
  app is not installed. Screen/camera/microphone/accessibility permissions and
  recorder-side visual effects are therefore not runtime-verified here. The
  external-app integration is verified at adapter, real-media ingest, schema,
  pipeline, and privacy-contract levels only.

Follow `docs/RELEASING.md` from a real upstream fork before publishing or
tagging a release.
