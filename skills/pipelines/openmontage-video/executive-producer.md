# Executive Producer — openmontage-video

This pipeline is a gated, instruction-driven production. Read the job first,
then run stages in manifest order. Never let a missing dependency become a
silent feature downgrade.

At idea, normalize the user's request into `projects/<id>/job.yaml` and run
`.agents/skills/openmontage-video/scripts/validate-job.py`. At assets, select
`provided`, `record`, or `mixed`; record mode must pass a dry-run before capture.
At edit, hold for the rough-cut checkpoint. At compose, hold for the
final-candidate checkpoint. Publish is allowed only after that approval.

When a feature is `off`, require a matching append-only decision-log entry. A
feature marked `required` has no fallback: HyperFrames failure blocks required
3D, and missing Playwright blocks record mode.
