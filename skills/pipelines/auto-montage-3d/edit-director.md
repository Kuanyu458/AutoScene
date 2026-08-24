# Edit Director — Auto Montage 3D

Call `beat_cut_planner` with the sole MusicTimingMap, ordered scene slots,
target frames, and the approved policy. The tool must emit
`edit_decisions@2.0`: `timeline.start_frame/end_frame`,
`source.ref/in_frame/out_frame`, and optional anchor ID/type/target/error.

Use section quota and minimum-spacing suppression before anchor snapping. On an
unreliable grid use phrase, hard-stop, energy, and pitch anchors only. Do not
invent beat precision. Enforce unique sources, source bounds, no gap, no
overlap, speed 1.0, and no freeze. If coverage is insufficient, checkpoint a
blocker and recommend more media or a shorter duration; never conceal the gap
with repeats.

Preserve the proposal's renderer family, render runtime, and composition mode.
Validate the artifact and verify all three runtime adapters derive the same
timeline placement and source trim from TimelineV2.
