---
name: openmontage-video
description: Build a reproducible OpenMontage product or website video from provided media, safe Playwright browser capture, or a mix, with beat-sync, HyperFrames 3D UI, and Recordly-style 2D UI evidence.
metadata:
  short-description: Open-source automated product video workflow
---

# `$openmontage-video`

Use this skill when a user wants an OpenMontage video workflow that can use
their own media, have the agent record a website, or combine both. It is a
thin router over the dedicated `openmontage-video` pipeline; do not bypass the
pipeline with one-off scripts or direct render calls.

## Route the request

1. Normalize the request into `projects/<project_id>/job.yaml` using
   [references/job-spec.md](references/job-spec.md), then run
   `scripts/validate-job.py`.
2. Select exactly one source mode: `provided`, `record`, or `mixed`. If the
   requested mode lacks media, a base URL, or declarative flows, ask for the
   missing input or for an explicit feature switch; never silently skip it.
3. Treat `features.beat_sync`, `features.ui_3d`, and `features.ui_capture` as
   `required` by default. Only the literal `off` is allowed, and it requires a
   matching append-only `decision_log` entry.
4. Read only the references needed for the selected mode, then execute
   `pipeline_defs/openmontage-video.yaml` stage by stage. Preserve the locked
   render runtime and versions.

## Non-negotiable capabilities

- **Beat sync:** analyze music with `audio_timing`, then snap only unlocked
  semantic markers within the job tolerance (default +/-250 ms).
- **3D UI:** when required, use native HyperFrames and prove two independent
  planes with perspective/translateZ/rotation over observable time. A slide,
  global shake, or zoom pulse is not 3D evidence. HyperFrames doctor/lint/
  validate/inspect failure is a blocker.
- **2D UI capture:** use `playwright_recorder` for the safe declarative browser
  flow, or import a user-provided Recordly MP4/WebM. `.recordly` project files
  are not parsed in v1.

## Capture safety

Use a fresh browser context and only localhost or explicitly allow-listed
origins. Allowed operations are `goto`, `click`, `fill`, `select`, `press`,
`scroll`, `wait`, `assert`, `hold`, and `screenshot`; arbitrary JavaScript,
shell, login, cookies, storage state, cross-origin iframes, and external
redirects are blocked. Read [references/recording-security.md](references/recording-security.md)
before a `record` or `mixed` job.

## Approval gates

Guided mode has three additional, independent stops:

1. assets: materials/music/script plus rights/privacy and audiomap;
2. edit: 720p rough cut and `rough_cut_report`;
3. compose: 1080p final candidate and `feature_evidence`.

Set the checkpoint to `awaiting_human`, present the artifacts, and end the
turn. Earlier approvals, silence, or "continue" do not approve the current
gate. Autonomous mode is permitted only when `job.yaml` explicitly authorizes
it; rights, credentials, privacy, and runtime blockers still stop the run.

Read [references/quality-and-approvals.md](references/quality-and-approvals.md)
when preparing a gate package. Read [references/beat-sync.md](references/beat-sync.md)
and [references/3d-ui.md](references/3d-ui.md) before edit/compose.

## Outputs

Default output is `projects/<project_id>/renders/final.mp4`, 1920x1080, 30 fps,
H.264/AAC. Keep `job.yaml`, `audiomap`, `rights_privacy_review`,
`rough_cut_report`, `feature_evidence`, final review, and decision history in
the project workspace. Public examples must use synthetic localhost data and
original/CC0 audio; never package user media, medical documents, credentials,
or unverified fonts.
