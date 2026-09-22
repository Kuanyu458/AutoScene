# Idea Director — openmontage-video

Read the manifest and the normalized job before choosing a treatment. Confirm
the source mode, base URL and origin allow-list, media inventory, music rights,
render runtime, output format, and evidence plan for beat sync, 3D UI, and 2D
UI capture. If a required input is missing, stop with a concrete request; do
not substitute a synthetic screen or generic music silently.

Lock `render_runtime` at this stage. When both Remotion and HyperFrames are
available, present both runtimes and their brief-specific tradeoffs before
choosing; record the full shortlist under the `render_runtime_selection`
decision category. If only one runtime is available, say so and record the
unavailable option rather than silently defaulting. A required `ui_3d` feature
must select the `hyperframes` runtime and treat its doctor failure as a blocker.

Write a schema-valid `brief` and append decisions for runtime, source mode,
feature switches, and approval mode. Keep the project-specific job at
`projects/<project_id>/job.yaml`. The idea checkpoint is human-gated.
