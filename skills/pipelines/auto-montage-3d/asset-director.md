# Asset Director — Auto Montage 3D

Read the `remotion-best-practices`, `threejs-fundamentals`, and
`threejs-animation` Layer 3 skills before calling `remotion_three_scene`.
Run `doctor` first. A missing Remotion/Three dependency or unavailable `angle`
backend is a blocker; do not disable 3D or change backend silently.

For each planned 3D scene, render into
`assets/procedural-3d/<scene-id>/`. The implementation must use
`useCurrentFrame()` only: no `useFrame()`, wall clock, CSS animation, remote
URL, Theatre.js, or model provider. Run `verify`, inspect the opening, middle,
ending, and every cue frame, and reject black or missing frames.

Add the verified MP4 to `asset_manifest` with `type=animation`,
`subtype=procedural_3d`, package path, render hash, backend
`remotion-three-angle`, cue frames, seed, and provenance. The MP4 is the only
3D artifact the final montage runtime consumes.
