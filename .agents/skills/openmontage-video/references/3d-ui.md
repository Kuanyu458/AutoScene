# Native 3D UI contract

When `ui_3d` is required, lock `render_runtime: hyperframes` at proposal and
run HyperFrames doctor, lint, validate, inspect, then render. Each evidence
scene must contain at least two independently positioned planes (for example,
a source card and a citation card), a real perspective value, observable
translateZ or rotation change, and one directional motion. Keep global scale
fixed; avoid shake, pulse zoom, and a full-frame slide masquerading as depth.

Record the scene contract in `edit_decisions.automation.ui_3d_scenes` with
`planes`, `perspective`, `translate_z`, `rotation`, `motion_direction`, and
`no_global_shake: true`. The compose stage must cite representative frames or
HyperFrames inspection output in `feature_evidence`.
