# AutoScene v0.2.0 beta local verification record

Verification date: 2026-08-24

This record distinguishes local runtime evidence, live repository settings,
and cross-platform claims. The verified checkout is the retained-history fork
`Kuanyu458/AutoScene` on local branch `codex/autoscene-beat3d-recordly`.

Git provenance was checked before import: the reconstructed source delta maps
to upstream commit `80e51fd6181736e856a138eaac1cbbb36dac54ab` and was integrated
onto fork/upstream `main` commit
`cd9f3c1f03368be87b140af494914b8ee4e3c7a4`. See `UPSTREAM.md`.

## Verified environment

| Component | Verified value |
|---|---|
| Host | macOS, Apple Silicon (`arm64`) |
| Python | 3.13.7 in the bootstrap-managed `.venv` |
| Node.js / npm | 22.22.3 / 10.9.8 |
| FFmpeg / ffprobe | 4.3.2 |
| Remotion family | 4.0.484 |
| `@remotion/three` | 4.0.484 |
| Three.js | 0.155.0 |
| React Three Fiber | 8.18.0 |

## Gates passed

- bootstrap completed with its virtualenv-local npm cache;
- `autoscene doctor` returned `READY` with no blockers (the `openmontage`
  compatibility alias remains available);
- `pip check` found no broken requirements;
- complete Python regression: 1,924 passed, 13 intentionally skipped, 3
  expected failures, and 1 subtest passed;
- TypeScript compiler: zero errors;
- Remotion enumerated 14 compositions, including the 1920x1080, 30 fps,
  60-frame `ProceduralThree` smoke composition;
- `npm audit --omit=dev --audit-level=high`: zero vulnerabilities after the
  reviewed exact transitive overrides in `docs/SECURITY_AUDIT.md`;
- public tracked tree: 2,174 files inspected, zero findings;
- both GitHub workflow YAML files parsed successfully;
- full-history high-signal scan found no private key, GitHub token, or AWS key
  pattern. The sole OpenAI-shaped match is an intentionally synthetic network-
  guard fixture retained in upstream test history; it is split in the current
  tree. GitHub secret scanning and push protection are enabled with zero open
  secret-scanning alerts.

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

Result: 1 passed in 25.94 seconds on the verified host.

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

## Live repository settings verified

- public repository: <https://github.com/Kuanyu458/AutoScene>;
- Issues, private vulnerability reporting, Dependabot security updates,
  dependency alerts, secret scanning, and push protection are enabled;
- the repository description is AutoScene-specific and no longer claims the
  upstream website as its homepage.

## Explicitly not yet verified

- The feature branch, Draft PR, and GitHub Actions status are intentionally
  verified during the publication step after this local record is committed.
- Ubuntu and Windows behavior is covered by authored Actions jobs but is not a
  local live-runtime claim. Treat the Draft PR checks as the current evidence.
- Linux and Windows live WebGL render parity is not claimed.
- HyperFrames remains optional and unavailable for live parity; the accepted
  beta E2E renderer is Remotion.
- A live Recordly GUI recording/export was not performed because the optional
  app is not installed. Screen/camera/microphone/accessibility permissions and
  recorder-side visual effects are therefore not runtime-verified here. The
  external-app integration is verified at adapter, real-media ingest, schema,
  pipeline, and privacy-contract levels only.

Do not tag a release until the Draft PR checks are green and their exact head
commit has been re-queried. Follow `docs/RELEASING.md`.
