# Recordly UI capture bridge

AutoScene can use [Recordly](https://github.com/webadderallorg/Recordly) as
an optional desktop recorder and editor for real product UI demos. Recordly is
installed and operated separately; AutoScene does not vendor, fork, bundle,
or automate its Electron application.

This bridge is intentionally split into two responsibilities:

1. Recordly records and edits the real UI session in its own visible desktop
   interface.
2. AutoScene imports an explicitly selected MP4, verifies it, copies it into
   the project without changing the source, and feeds it to the `screen-demo`
   pipeline as a normal video asset.

The result is usable on another computer without making Recordly a Python or
Node dependency of AutoScene.

## Supported workflow

1. Install Recordly from its
   [official releases](https://github.com/webadderallorg/Recordly/releases).
2. Open Recordly and choose the screen/window, microphone, system audio, and
   optional camera.
3. Record the product workflow, then apply Recordly's cursor treatment, zooms,
   framing, annotations, and trims.
4. Export an MP4 to a path you choose.
5. Ask the AutoScene agent to use `screen-demo` with
   `production_mode=real_capture` and `capture_backend=recordly`, then provide
   that exact MP4 path for `recordly_recorder` ingestion.
6. Review the privacy report. Publishing is blocked while any sensitive region
   remains unresolved.

Recordly remains a human-operated step. A successful launch or installation
check is not evidence that a recording was completed. The bridge only reports
capture success after a selected MP4 has been copied, probed, hashed, and
packaged.

## Tool contract

`recordly_recorder` is discovered through the existing
`capability="screen_capture"` registry seam. Its public operations are:

| Operation | Purpose |
|---|---|
| `doctor` | Detect the external app, platform support, ffprobe, and permission caveats without launching anything. |
| `setup_guide` | Return official installation and capture instructions. It does not install software. |
| `launch` | Open Recordly only after an explicit call and return `awaiting_human`; it never claims that recording finished. |
| `ingest` | Read one explicit exported MP4, copy it into a new project location, probe it, hash it, and write `ScreenCapturePackage@1.0`. |
| `verify` | Recheck the package schema, staged media hash, media probe, and source-mutation evidence. |

`screen_capture_selector` exposes Recordly alongside FFmpeg and Cap. Its
existing `auto` behavior stays automation-first. For a polished product demo,
set `capture_intent=polished_product_demo` or explicitly choose
`preferred_provider=recordly`. Playwright capture remains the preferred option
for deterministic browser-only flows.

## Portable package

The canonical package stores an MP4 path relative to the directory containing
`screen_capture_package.json`, plus its SHA-256 hash, technical probe, capture
backend, upstream provenance, source-mutation check, and privacy review. The
asset manifest separately records the path relative to the AutoScene project.
Neither artifact persists the user's original absolute input path.

Recordly's `.recordly` project format is not the portable handoff contract. At
the reviewed upstream snapshot it is JSON that references source media by
absolute path, so copying that file alone to another computer is insufficient
and may disclose local paths. Export MP4 instead.

## Privacy gate

Real UI recordings may contain account names, email addresses, notifications,
tokens, customer data, private tabs, or microphone/camera content. Before
publish, the `final_review.checks.privacy` result must be `pass`, every declared
sensitive region must be resolved by masking, exclusion, or a confirmed
non-sensitive classification, and `unresolved_items` must be empty.

AutoScene does not scan the user's home directory or Recordly's private
application-data directory to guess which recording to use. The MP4 must be
selected explicitly. Ingestion copies; it never moves, edits, or deletes the
source.

## Platform notes

| Platform | Recordly upstream requirement | AutoScene contract |
|---|---|---|
| macOS | macOS 14+; Screen Recording and related permissions are user-controlled | app detection plus explicit MP4 ingestion |
| Windows | Windows 10 build 19041+ recommended by upstream | install-path contract plus explicit MP4 ingestion |
| Linux | modern x86_64 distribution; system audio commonly needs PipeWire | AppImage/PATH detection plus explicit MP4 ingestion; double-cursor risk must be reviewed |

Installation detection does not prove screen, microphone, camera, accessibility,
or portal permission. `doctor` reports those permissions as user-verifiable
rather than silently assuming they were granted.

## Upstream and license boundary

The integration was designed against Recordly commit
[`72e9724505e2498fd85754cfe69e02d8a69900a0`](https://github.com/webadderallorg/Recordly/commit/72e9724505e2498fd85754cfe69e02d8a69900a0).
Recordly is an external AGPLv3 project with project-specific attribution and
branding terms in its own license file. No Recordly source code or branding is
copied into AutoScene, and this project is not affiliated with or endorsed by
Recordly. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

The inspected upstream tree contains private smoke-export environment variables,
but no documented stable headless API. AutoScene deliberately does not depend
on that test-only interface.
