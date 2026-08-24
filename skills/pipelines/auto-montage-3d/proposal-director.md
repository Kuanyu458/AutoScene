# Proposal Director — Auto Montage 3D

Present 2-3 differentiated montage concepts grounded in the actual source
inventory and MusicTimingMap. For each, state pacing density, source/3D ratio,
3D insertion anchors, expected duration, local cost, and runtime requirements.

Resolve `adaptive` to `beat_cut` only when the timing map says the grid is
reliable; otherwise resolve to `phrase_flow`. The default 3D count is
`clamp(ceil(duration_seconds / 20), 1, 3)` and every insert is 2-4 bars on a
phrase, drop, or hard-stop anchor.

Follow AGENT_GUIDE runtime governance. The alternative `hyperframes` runtime
is referred to by its product name HyperFrames below. If both Remotion and HyperFrames are
available, Present both and wait for the user. Record the complete shortlist
as a `render_runtime_selection` decision and carry the approved value in
`render_runtime`. If HyperFrames is unavailable,
say so and record it as rejected for that reason. v1's tested production path
is Remotion, with procedural 3D pre-rendered by Remotion/Three and inserted as
ordinary video. Present templated versus atelier as a separate decision; this
automatic beta pipeline recommends templated. Record all options and approval
in `decision_log`, and write `beat_sync_policy` plus `three_d_plan` into the
proposal packet.
