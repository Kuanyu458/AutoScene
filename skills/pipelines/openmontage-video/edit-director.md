# Edit Director — openmontage-video

Build the rough cut from semantic decisions first. Use `audio_timing.snap_markers`
only for unlocked markers; the nearest valid beat/onset must be within
`job.edit.snap_tolerance_ms` (default 250 ms). Preserve result holds and
subtitle readability over a forced musical hit.

Each 2D UI scene has at most one purposeful focus event anchored to a real
click/result. 3D UI scenes must show two planes with perspective and a
single-direction transform; no global shake or repeated scale pulse. Extend
`edit_decisions.automation` with the beat map, focus events, and 3D contracts.

Render a 720p H.264 rough cut and write `rough_cut_report` with known issues,
script deltas, and the change list. Stop at the rough-cut approval checkpoint.
