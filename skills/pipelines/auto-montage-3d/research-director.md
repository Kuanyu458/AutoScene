# Research Director — Auto Montage 3D

Treat the input folder as read-only. Resolve it with `MontageRequest@1.0`, copy
each brief, music, image, and video into a fresh `projects/<slug>/`, and verify
the staged bytes against the source SHA-256. Never overwrite an existing slug.

Run registry preflight before analysis. Probe every media file, detect source
shot windows, and sample representative frames. Write those observed windows
to `source_media_review`; do not perform ASR/MLLM semantic selection in v1.

Run `music_sync_analyzer` exactly once for the approved music file and keep its
`MusicTimingMap@1.0` as the sole music timing authority. If confidence is below
0.60 or `grid_reliable=false`, record `phrase_flow`; never infer a better BPM by
ear or run another analyzer. If the track exceeds 60 seconds, choose one best
60-second window whose start and end are phrase boundaries and record the
offset. Produce a local-only research brief and checkpoint all supplementary
artifacts.
