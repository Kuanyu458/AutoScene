# Publish Director - Screen Demo Pipeline

## When To Use

Package the finished demo so the user can publish it quickly and so the metadata reflects the actual task, result, and tools involved.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["compose"]["final_review"]`, `state.artifacts["idea"]["brief"]`, `state.artifacts["script"]["script"]`, optional `screen_capture_package` | Video, review evidence, brief, and sections |
| Playbook | Active style playbook | Thumbnail and copy tone |

## Process

### 0. Privacy gate before packaging

Read `brief.metadata.production_mode` before creating any publish package.

For `real_capture`, publishing is blocked unless all of these are true:

- `final_review.status == "pass"`,
- `final_review.checks.privacy.required == true`,
- `final_review.checks.privacy.passed == true`,
- `final_review.checks.privacy.unresolved_sensitive_regions == 0`,
- `final_review.checks.privacy.redactions_verified == true`,
- the staged MP4 still matches the SHA-256 recorded in its
  `ScreenCapturePackage@1.0`.

If the privacy object is missing, treat it as failure, not as “no issues.” Stop
at the checkpoint and identify the frames that need review without repeating
the sensitive values in logs. This gate applies equally to Recordly, Cap,
FFmpeg, Playwright, and user-supplied real screen captures. Synthetic terminal
or synthetic UI scenes that never captured a user screen do not require this
object.

### 1. Build Searchable Metadata

Screen-demo titles work best when they combine:

- task,
- tool,
- outcome.

Good patterns:

- `How to deploy on Vercel from Next.js`
- `Fix CORS in React + Express`
- `Set up GitHub Actions for Python tests`

Pull keywords from:

- software names,
- frameworks,
- commands,
- exact error text,
- outcome words such as `deploy`, `fix`, `connect`, `publish`, `ship`.

### 2. Use Chapter Markers As Navigation

Use script sections as the basis for chapter markers and packaging bullets. A good screen-demo package makes the workflow skimmable before the user even presses play.

### 3. Thumbnail Strategy

If a thumbnail concept is needed, it should show:

- the result state, not a generic setup screen,
- the recognizable tool surface,
- 2-4 words of value text.

Store the concept in `publish_log.metadata.thumbnail_concepts`.

### 4. Package By Platform

Prepare:

- video file,
- title and description/caption,
- chapter markers where relevant,
- keyword list,
- thumbnail concept notes.

For a Recordly-sourced demo, export only the approved final video and normal
publish metadata. Do not ship the raw `.recordly` editor project, absolute-path
session JSON, recording diagnostics, local recordings directory, or unredacted
source MP4. Strip absolute user paths from diagnostics and provenance before
sharing any report.

For developer or product-demo content, also package:

- commands shown,
- software/version mentions,
- error terms if it is a troubleshooting demo.

### 5. Quality Gate

- metadata names the real tool and task,
- chapters match the actual rendered flow,
- export folders are clean and reusable,
- copy is tailored to the platform instead of duplicated.
- every real-capture privacy condition in the gate above still passes on the
  exact file being packaged.

## Common Pitfalls

- Publishing with generic titles that omit the actual software or task.
- Using the same caption for YouTube, LinkedIn, and short-form social.
- Building chapter markers from the script without checking the render.
- Treating a successful Recordly ingest as privacy approval.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
