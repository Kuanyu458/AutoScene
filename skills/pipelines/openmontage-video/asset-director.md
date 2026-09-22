# Asset Director — openmontage-video

Review supplied media for technical validity, rights, and privacy. Recordly
imports are MP4/WebM only; never parse or execute `.recordly` files. For
`record` or `mixed` flows, call `playwright_recorder` in `dry_run` first and
stop if origin, selector, credential, or dependency checks fail. Then record
to the project assets directory and preserve the manifest, focus map, contact
sheet, hash, and privacy report.

Analyze supplied music with `audio_timing` unless beat sync is explicitly off
and logged. Keep an append-only `rights_privacy_review`, `audiomap`, and
asset_manifest. Submit the complete materials/music/script review package;
guided mode stops at `awaiting_human`.
