# Beat-aware timing

Run `audio_timing analyze` on the chosen music and persist `audiomap`. Script
and scene-plan times are semantic first. For each candidate marker:

- `semantic_locked: true` keeps the nominal time exactly;
- unlocked markers may snap to a beat, downbeat, or onset;
- the nearest candidate must be within `edit.snap_tolerance_ms` (default 250);
- if no candidate is within tolerance, stop for review rather than force a cut.

`edit_decisions.automation.beat_sync` records the audiomap path, tolerance,
and applied marker list. The legacy
`.agents/skills/music-to-video/scripts/analyze-beatgrid.py` CLI remains
compatible; the registry tool is the canonical pipeline interface.
