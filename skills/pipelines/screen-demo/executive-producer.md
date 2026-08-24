# Executive Producer — Screen-Demo Pipeline

## When to Use

You are the **Executive Producer (EP)** for a screen-demo video. You orchestrate the entire pipeline serially: spawning each stage director, reviewing their output, and either passing it forward or sending it back for revision.

**This pipeline has no pre-production checkpoint stages** (no research, no
proposal). In `real_capture`, source footage either already exists or is
acquired through the idea-stage capture preflight and stored as a verified
`ScreenCapturePackage@1.0`. The capture preflight does not create a new stage.
The EP adds cross-stage quality gates that catch privacy, provenance,
legibility, audio clarity, and pacing issues early—before the expensive compose
step.

## Why This Exists

Screen-demo videos have specific failure modes that parallel execution misses:

- Text in screen recordings becomes unreadable after crops and scaling
- Zoom-crop regions that looked fine in planning obscure critical UI elements in practice
- Keyboard noise and background hum survive into the final render
- Dead time (loading screens, typing pauses) makes videos unwatchable without speed adjustments
- Callout overlays block the very UI they're trying to highlight
- Subtitle positioning conflicts with screen content

The EP catches all of these at the earliest possible stage.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Pipeline | `pipeline_defs/screen-demo.yaml` | Stage definitions, review focus, success criteria |
| Skills | All 7 director skills + `meta/reviewer` | Stage execution knowledge |
| Schemas | All artifact schemas | Validation |
| Playbook | Active style playbook | Quality constraints |
| Tools | Full tool registry | Available capabilities |

## Cumulative State

```
EP_STATE:
  pipeline: screen-demo
  playbook: <selected playbook name>
  target_duration_seconds: <from brief or estimated from source>
  budget_total_usd: <configured limit>
  budget_spent_usd: 0.0
  budget_remaining_usd: <budget_total>

  # Screen-demo specific state
  source_resolution: null       # original recording resolution
  target_resolution: null       # output resolution
  has_voiceover: false          # does source have narration audio?
  has_keyboard_noise: false     # flagged during script/asset stage
  zoom_regions: []              # crop regions from scene plan, for cross-checking
  capture_backend: null         # recordly / ffmpeg / cap / playwright
  screen_capture_package: null  # portable package for real_capture
  privacy_status: null          # pending / passed / blocked

  # Accumulated from each stage (7 stages)
  artifacts:
    idea: null          # → brief
    script: null        # → script
    scene_plan: null    # → scene_plan
    assets: null        # → asset_manifest
    edit: null          # → edit_decisions
    compose: null       # → render_report
    publish: null       # → publish_log

  # Cross-stage tracking
  narration_durations: {}
  style_anchors: {}
  revision_counts: {}
  issues_log: []
```

## Execution Protocol

### Phase 0: Initialize

1. Load the pipeline manifest (`screen-demo.yaml`)
2. Load the playbook (from user selection or default)
3. Set budget from configuration or user input (default: $1.00 — screen-demo is typically low-cost)
4. Initialize EP_STATE
5. If `production_mode=real_capture` and no verified source is staged, run the
   idea-director capture preflight. A Recordly launch returns
   `awaiting_human`; pause for the user to record/export, then ingest only the
   exact MP4 they select. Do not scan Recordly user data or treat launch as a
   completed capture.

### Phase 1: Execute Stages Serially

For each stage in order: `idea → script → scene_plan → assets → edit → compose → publish`

```
EXECUTE_STAGE(stage_name):

  1. PREPARE
     - Load the director skill for this stage
     - Inject EP_STATE as context
     - Inject any EP feedback from previous revision attempts

  2. SPAWN DIRECTOR
     - Director executes its full process
     - Director produces an artifact

  3. REVIEW
     - Schema validation
     - Check review_focus from pipeline manifest
     - Check success_criteria from pipeline manifest
     - Run EP-SPECIFIC CROSS-STAGE CHECKS (see below)

  4. GATE DECISION
     If PASS → store artifact, update tracking, continue
     If REVISE → increment revision count, re-run with feedback (max 3)
     If SEND_BACK(target_stage) → re-execute from target forward (max 1 per pair)
```

### Phase 2: Final Quality Assurance

```
FINAL_QA:
  1. PROBE the output video:
     - Duration: reasonable for the demo content?
     - Resolution: matches target?
     - Audio: voiceover clear? Keyboard noise removed?
     - File: valid container, reasonable size?

  2. LEGIBILITY CHECK (SCREEN-DEMO CRITICAL):
     - Is UI text readable at the output resolution?
     - Are zoom-crop regions showing the intended UI elements?
     - Are callout overlays not obscuring critical content?

  3. PACING CHECK:
     - Are loading/typing pauses sped up or cut?
     - Does the demo flow logically?
     - Are transitions between workflow steps smooth?

  4. SUBTITLE CHECK:
     - Do subtitles not overlap with screen content?
     - Is subtitle timing accurate to speech?

  5. BUDGET RECONCILIATION:
     - Total actual spend vs. budget
     - Log per-stage cost breakdown

  6. PRIVACY GATE (REAL CAPTURE):
     - ScreenCapturePackage hash and package-relative MP4 still verify?
     - Every sensitive frame range resolved in the rendered output?
     - final_review.checks.privacy.passed is true?
     - unresolved_sensitive_regions is zero and redactions_verified is true?

  7. DECISION:
     If all pass → APPROVE for publish
     If legibility issues → send back to compose (re-render) or scene (replan crops)
     If audio issues → send back to compose (re-mix)
     If pacing issues → send back to edit (re-time)
```

## EP-Specific Cross-Stage Checks

### After IDEA stage:
```
CHECK: Source assessment
  - Is source footage referenced and accessible?
  - For real_capture, is the capture backend explicit?
  - If a capture adapter was used, is ScreenCapturePackage schema-valid and hash-verified?
  - Is the capture privacy state explicit? Pending is valid for editing, never for publishing.
  - Is target platform and duration realistic?
  - Are callout/zoom needs identified?
  - If no source footage: STOP — this pipeline requires source footage
```

### After SCRIPT stage:
```
CHECK: Transcript quality
  - If source has voiceover: is transcript accurate and timestamped?
  - Are key UI actions annotated with timestamps?
  - Are workflow steps clearly segmented?
  - Flag keyboard noise presence for asset stage

CHECK: Duration estimate
  - Estimated output duration reasonable for the content?
  - If demo is > 5 minutes: suggest trimming or speed adjustments
```

### After SCENE_PLAN stage:
```
CHECK: Zoom-crop feasibility
  - For each crop region: does it capture the intended UI element?
  - Are crop regions at least 50% of source resolution? (avoid extreme zooms that pixelate)
  - Store zoom_regions in EP_STATE for compose verification

CHECK: Callout placement
  - Do callout overlays (arrows, highlights, masks) avoid obscuring the UI element they reference?
  - Are callouts sparse? (max 2-3 concurrent callouts)

CHECK: Pacing plan
  - Are dead-time segments (loading, typing) flagged for speed-up or cut?
  - Are speed changes smooth (not jarring jumps)?
```

### After ASSETS stage:
```
CHECK: Subtitle positioning
  - Do subtitles avoid overlapping with key screen content?
  - Is subtitle font readable against screen background?

CHECK: Audio quality
  - If audio_enhance was used: is keyboard noise reduced?
  - If TTS was generated: does narration timing match screen actions?

CHECK: Budget gate
  - If budget_spent > budget_total * 0.9 and stages remain:
      Alert and adjust remaining stages

CHECK: Sensitive-region plan (real_capture)
  - Every detected credential, notification, private tab, or personal-data range has a frame range and planned blur/crop/cut action
  - Artifacts contain categories and coordinates only, never the captured secret value
```

### After EDIT stage:
```
CHECK: Timeline completeness
  - All edit decisions reference valid source files and assets
  - Audio ducking configured if background music added
  - Speed adjustments are smooth (ramp, not jump)

CHECK: Dead time handling
  - Loading screens and typing pauses either cut or sped up
  - Total dead time < 10% of output duration
```

### After COMPOSE stage:
```
CHECK: Output validation
  - ffprobe: duration, resolution, codec, audio channels
  - Text readability at output resolution
  - Audio clarity — voiceover intelligible throughout

CHECK: Screen sharpness (SCREEN-DEMO CRITICAL)
  - UI text in the recording must be readable
  - If crops caused pixelation: flag for scene plan revision
  - Anti-aliased text must survive compression

CHECK: Privacy render evidence (REAL-CAPTURE CRITICAL)
  - Inspect mask entry/exit frames, not only the middle of each range
  - final_review.checks.privacy is present and passed
  - unresolved_sensitive_regions == 0
  - redactions_verified == true
  - If any condition fails: block publish and send back to assets/edit/compose
```

## Feedback Message Templates

### To Script Director:
```
EP FEEDBACK — Script Revision Required
Reason: {reason}
Specific issue: {transcript_accuracy / segmentation / timing}
Keep: {what was good}
Change: {what specifically needs to change}
```

### To Scene Director:
```
EP FEEDBACK — Scene Plan Revision Required
Reason: {reason}
Affected scenes: {scene_ids}
Constraint: {crop_feasibility / callout_placement / pacing}
Source resolution: {W}x{H} — minimum crop: {W/2}x{H/2}
```

### To Compose Director:
```
EP FEEDBACK — Re-render Required
Reason: {reason}
Specific issue: {legibility / audio / pacing}
Expected: {what the output should look/sound like}
Actual: {what was produced}
```

## Quality Gates Summary

| Gate | After Stage | What's Checked | Fail Action |
|------|-------------|---------------|-------------|
| G1 | idea | Source/capture package, backend, privacy plan, feasibility | Revise idea or wait for capture |
| G2 | script | Transcript accuracy, duration estimate | Revise script |
| G3 | scene_plan | Crop feasibility, callout placement, pacing plan | Revise scene_plan |
| G4 | assets | Subtitle positioning, audio quality, sensitive-region plan, budget | Revise assets |
| G5 | edit | Timeline completeness, dead time handling | Revise edit |
| G6 | compose | Output probe, screen sharpness, audio clarity, rendered privacy evidence | Revise compose OR send-back |
| G7 | publish | Privacy passed, metadata, chapters, export packaging | Block or revise publish |
| FINAL | all | Legibility, pacing, subtitles, audio | Send-back to specific stage |

## Execution Limits

| Limit | Value | Rationale |
|-------|-------|-----------|
| Max revisions per stage | 3 | Prevent perfectionism loops |
| Max send-backs per stage pair | 1 | Prevent ping-pong |
| Max total send-backs | 3 | Cap total re-work |
| Max total budget | Configurable (default $1) | Hard stop on spending |
| Max total wall-time | 10 minutes | Screen-demo is simpler than generated pipelines |

## Common Pitfalls

- **Ignoring text readability**: The #1 screen-demo issue. Always verify UI text is readable after crops.
- **Over-cropping**: Extreme zooms pixelate. Minimum crop should be 50% of source resolution.
- **Leaving dead time**: Loading screens and typing pauses must be handled. Speed-up or cut.
- **Callout overload**: More than 2-3 concurrent callouts creates visual chaos.
- **Ignoring keyboard noise**: If the source has keyboard sounds, flag it early for audio cleanup.
