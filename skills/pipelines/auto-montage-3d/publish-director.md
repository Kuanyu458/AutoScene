# Publish Director — Auto Montage 3D

This stage packages local output only. Do not upload or message external
systems. Require `final_review.status=pass`, then verify the final MP4,
contact-sheet, artifacts, decision log, source hashes, and run summary are all
present under the project directory.

The publish log records beta pipeline version, source inventory hash, music
offset, resolved pacing policy, runtime, composition mode, 3D backend, QA
metrics, and absolute final path. State that macOS Apple Silicon is the tested
platform; do not claim Windows or live HyperFrames parity without a separate
successful run.
