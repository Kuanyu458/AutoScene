# Auto Montage 3D pipeline contract

`auto-montage-3d` is a beta OpenMontage pipeline for prepared media folders.
It intentionally excludes long-form ASR/MLLM semantic shot selection.

## Input contract

`MontageRequest@1.0` requires:

- a readable input directory;
- `brief.md`, `brief.txt`, or an explicit brief path;
- exactly one discovered music file or an explicit music path;
- at least one video or image;
- default 1920×1080, 30 fps, adaptive timing, and 3D enabled.

`openmontage init` is the public seam. Discovery priority is explicit path,
conventional filename, then a unique matching file. Inputs are copied into a
fresh project and hash-verified; explicit slug collisions fail.

## Canonical stages

| Stage | Work | Primary contract |
|---|---|---|
| research | probe media, shot windows, analyze music once | `source_media_review`, `MusicTimingMap@1.0` |
| proposal | concept, duration/window, beat policy, runtime and 3D plan | `proposal_packet` |
| scene_plan | ordered source/3D slots and narrative roles | `scene_plan` |
| assets | render and verify seeded procedural 3D | `asset_manifest`, `ThreeScenePackage@1.0` |
| edit | section quotas, anchors, dedupe, frame timeline | `edit_decisions@2.0` |
| compose | locked runtime render and exact-duration normalization | `render_report` |
| publish | local deliverable and final QA | `final_review` |

No custom checkpoint stage and no Python creative orchestrator are introduced.

## Music timing

`MusicSyncAnalyzer.execute({input_path, output_path})` is the only timing-map
producer. It records source hash/version, BPM/confidence, grid reliability,
beats, downbeats, onsets, pitch changes, energy, phrases, hard stops, sections,
and stable anchor IDs.

When confidence is below `0.60` or the grid is unstable, `adaptive` resolves to
`phrase_flow`. The pipeline must never present an unreliable estimate as a
precise beat grid.

If duration is unspecified, music at or below 60 seconds uses the full track.
Longer tracks use a phrase-closed best window of at most 60 seconds, with the
offset surfaced in the proposal.

## Edit timeline

TimelineV2 makes integer frames authoritative:

```json
{
  "timeline": {"start_frame": 0, "end_frame": 60},
  "source": {"in_frame": 15, "out_frame": 75},
  "anchor": {
    "id": "downbeat-004",
    "type": "downbeat",
    "target_frame": 60,
    "error_frames": 0
  }
}
```

One normalization module migrates legacy v1 decisions. FFmpeg, Remotion, and
HyperFrames consume runtime adapters from the same canonical timeline rather
than independently interpreting seconds.

The native planner uses section-aware quotas, energy/pitch/downbeat anchors,
minimum-spacing suppression, source deduplication, and boundary clamping. It
does not repeat, freeze, or change source speed unless the approved request
explicitly permits it. Insufficient unique coverage is a blocker.

## Procedural 3D

`remotion_three_scene.execute({operation, scene_spec, timing_map, output_dir})`
supports `doctor`, `render`, and `verify`.

v1 invariants:

- templates: `ui-depth-stack`, `orbital-reveal`, `data-constellation`;
- 1920×1080, 30 fps, H.264 full-frame inserts;
- seeded parameters and fixed ANGLE backend;
- frame-driven `useCurrentFrame()` animation;
- no `useFrame()`, wall clock, CSS animation, Theatre.js, remote asset request,
  transparent overlay, GLB generation, or prompt-to-model provider;
- sampled previews, non-black checks, cue-frame verification, and hashes.

The default scene count is `clamp(ceil(duration/20), 1, 3)`. Each insert lasts
2–4 bars and lands on an approved phrase, drop, or hard-stop anchor.

## Runtime governance

The proposal records all available composition runtimes and locks the user's
choice. Compose must preserve it. Missing runtime/GL support or 3D render
failure is a structured blocker; silent fallback is forbidden.

Remotion is the only live E2E-verified renderer for v1. HyperFrames remains an
optional OpenMontage runtime and is not claimed as live Beat3D parity here.

## Methodology and CutClaw boundary

The design cites CutClaw's public discussion of music structure,
section-aware allocation, and review, plus its paper. The implementation is an
independent native planner with OpenMontage contracts.

- snapshot: <https://github.com/GVCLab/CutClaw/commit/db48d08b0d48881df0dda0b207b6873148c88077>
- paper: <https://arxiv.org/abs/2603.29664>

CutClaw is not a dependency, submodule, import, CLI, or renderer. No code is
copied into this repository. The contract test
`tests/contracts/test_cutclaw_license_boundary.py` enforces that boundary.

## Acceptance

The macOS E2E uses only locally generated clips and a 120 BPM click track. It
checks unchanged source hashes, schema-valid artifacts, at least one source and
one 3D insert, H.264/AAC output, 1920×1080 at 30 fps, duration within one frame,
planner alignment within one frame, rendered p95 within two frames, A/V drift
within 100 ms, and no black/missing/silent fallback.
