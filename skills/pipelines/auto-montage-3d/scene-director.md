# Scene Director — Auto Montage 3D

Build ordered slots that tile the approved music window. Each source slot must
reference an observed shot window with enough unique frames. Do not repeat a
source, freeze a frame, or change playback speed unless the approved proposal
explicitly allows it.

Distribute source slots using each section's measured energy and density. Place
the approved number of `procedural_3d` scenes at phrase, energy-change, drop, or
hard-stop anchors. Each 3D scene contains a `three_scene` block with one of
`ui-depth-stack`, `orbital-reveal`, or `data-constellation`, a stable seed,
duration in frames, anchor ID, beat cue frames, theme, camera, lighting, and
content. Each insert lasts 2-4 bars. Use frame math at 30fps as the planning
authority even though scene_plan retains seconds for canonical compatibility.
