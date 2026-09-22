# Quality and approval package

Assets gate: show the complete script, media/contact-sheet inventory, music
preview and rights note, audiomap, 3D representative frames, and the privacy
report. Edit gate: show a 720p H.264 rough cut, known issues, script deltas,
and a change list. Compose gate: show the 1920×1080 final candidate, decode and
audio checks, safe-area/subtitle review, final rights status, and feature
evidence for beat sync, 3D UI, and 2D capture/import.

In guided mode the checkpoint status is `awaiting_human`; approval text must
identify the current gate (for example, `通過：初剪`). A later or generic
“continue” does not satisfy an earlier or different gate. Revisions increment
the candidate version and preserve old artifacts; append every decision with a
timestamp rather than editing history in place.
