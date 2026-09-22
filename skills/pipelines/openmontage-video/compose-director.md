# Compose Director — openmontage-video

Carry the locked `render_runtime` forward. Pass the manifest's exact
`hyperframes` version (currently `0.7.109`) into `video_compose`/
`hyperframes_compose`; do not resolve an unpinned latest package. If `ui_3d` is required, HyperFrames
must pass doctor/lint/validate/inspect and render the 3D scene; do not replace
it with FFmpeg, Remotion, or a 2D slide. If the feature is off, cite its
decision-log entry in `feature_evidence`.

Produce the 1920x1080 final candidate at the requested fps with H.264/AAC,
then verify duration, decode, safe areas, subtitle legibility, audio peak, and
the three feature evidence entries. Hold at `awaiting_human` until the explicit
final-candidate approval is received.
