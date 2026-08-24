# Compose Director - Screen Demo Pipeline

## When To Use

Render the final screen-demo outputs. The quality bar is simple: the UI must be readable, the pacing must feel intentional, and the result must match the planned platform shapes.

## Runtime Routing (MANDATORY first step)

Read `edit_decisions.render_runtime` first. Screen-demo compositions use three distinct runtimes depending on the demo shape:

- **`render_runtime="remotion"` with `TerminalScene`** — the preferred path for synthetic terminal/CLI/install flows. See `.agents/skills/synthetic-screen-recording/`.
- **`render_runtime="remotion"`** (other scenes) — for mixed screen-capture + animated overlays.
- **`render_runtime="hyperframes"`** — for custom synthetic HTML UI demos where CSS + GSAP express the UI naturally. Read `skills/core/hyperframes.md`. `hyperframes lint` and `hyperframes validate` must both pass before render.
- **`render_runtime="ffmpeg"`** — for simple cut/concat of real screen recordings without composition.

Silent swaps between runtimes are CRITICAL governance violations. If the locked runtime is unavailable, escalate per AGENT_GUIDE.md before substituting.

**Pass `proposal_packet` to `video_compose.execute()`** so the tool can directly confirm the runtime locked at proposal matches what edit_decisions says. Without it the in-tool swap check is skipped and you rely entirely on the reviewer skill to catch drift.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json`, `schemas/artifacts/final_review.schema.json`, `schemas/artifacts/screen_capture_package.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["edit"]["edit_decisions"]`, `state.artifacts["assets"]["asset_manifest"]`, optional `screen_capture_package` | What to render |
| Tools | `video_compose`, `audio_mixer`, `video_trimmer` | Rendering capabilities |
| Playbook | Active style playbook | Quality targets |

## Process

### 1. Render For Legibility First

Prefer the simplest reliable render chain:

- trim and speed-adjust source footage,
- compose overlays and subtitles,
- mix audio only as much as needed,
- encode at a bitrate suitable for text-heavy content.

For `production_mode="real_capture"`, resolve `video.relative_path` from the
directory containing `screen_capture_package.json` and fail before rendering if
the staged MP4 is missing, escapes that package directory, or no longer matches
the SHA-256 in `ScreenCapturePackage@1.0`. The corresponding asset-manifest path
remains project-relative. Recordly capture is an ordinary verified video asset
after ingestion; the compose stage must not reopen its raw editor project or
recover a machine-specific source path.

### 2. Choose Output Shapes Pragmatically

| Platform | Aspect Ratio | Resolution | Notes |
|----------|--------------|------------|-------|
| YouTube / docs | `16:9` | 1920x1080 or higher | safest default for dense UI |
| LinkedIn feed | `1:1` | 1080x1080 | good compromise when vertical is too tight |
| Shorts / Reels / TikTok | `9:16` | 1080x1920 | only if crop plan is actually readable |

If the source is 4K and text is tiny, keep a higher resolution when practical.

### 3. Compose In The Right Order

1. apply trims and speed changes,
2. apply crop and framing strategy,
3. place masks and overlays,
4. burn subtitles,
5. mix audio,
6. encode with text-preserving settings.

Use sharp scaling and avoid aggressive compression. Screen text is the first thing viewers notice when encode quality drops.

### 4. Keep Audio Honest

- preserve original speech clarity,
- do not overcompress,
- mute or simplify useless sped-up noise,
- use music sparingly, if at all.

### 5. Verify Every Output

**File checks:**
- [ ] Output file exists and is a valid MP4 container
- [ ] Duration matches effective target within +/-5%
- [ ] Resolution matches selected profile

**Visual spot checks:**
- [ ] Text is sharp and readable at sampled frames
- [ ] Crop transitions are smooth enough to follow
- [ ] Callout overlays appear and disappear cleanly
- [ ] Blur masks fully cover sensitive data
- [ ] No black frames or timing glitches
- [ ] Subtitles do not sit on top of critical UI

**Privacy checks for every real capture:**

- [ ] Inspect the opening, ending, regular interval samples, and the start,
      middle, and end of every declared sensitive frame range
- [ ] Check mask entry/exit frames so a credential or notification does not
      flash for one frame before or after the mask
- [ ] Confirm every sensitive region is resolved and every required redaction is
      visible in the rendered output—not merely present in the edit plan
- [ ] Confirm review notes contain categories and frame ranges only, never the
      captured secret or personal value

Populate `final_review.checks.privacy` for `real_capture` with:

```yaml
required: true
source_package_ref: artifacts/screen_capture_package.json
reviewed_frames: 12
sensitive_regions_detected: 2
unresolved_sensitive_regions: 0
redactions_verified: true
passed: true
issues: []
```

`final_review.status="pass"` is forbidden unless `privacy.passed=true`,
`privacy.unresolved_sensitive_regions=0`, and
`privacy.redactions_verified=true`. Missing privacy evidence, a failed hash,
or even one unresolved frame makes the review `revise` or `fail` with
`recommended_action="block"` or an appropriate revision action. Synthetic
terminal/UI work may omit the privacy object because no user screen was
captured.

**Audio spot checks:**
- [ ] Narration/voiceover is clear and consistent volume
- [ ] Music, if used, is not competing with speech
- [ ] No obvious audio glitches at speed boundaries
- [ ] No clipping or distortion

Record important findings in:

- `render_report.verification_notes`
- `render_report.warnings`
- `render_report.metadata.variant_notes`
- `final_review.checks.privacy`

## Common Pitfalls

- Rendering `9:16` versions that are technically exported but practically unreadable.
- Encoding screen text with generic low-bitrate social defaults.
- Letting decorative backgrounds or padding reduce usable UI area too far.
- Passing a real capture because masks were planned without inspecting the
  rendered mask boundaries.
