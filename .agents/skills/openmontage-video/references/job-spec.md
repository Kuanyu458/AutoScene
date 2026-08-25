# Job specification

`job.yaml` is the portable input contract. Keep it free of credentials and
private browser state. The validator fills only documented defaults:

```yaml
version: "1.0"
project_id: product-launch
source:
  mode: provided # provided | record | mixed
  media:
    - path: assets/video/demo.mp4
      media_type: video
recording:
  base_url: http://127.0.0.1:8000
  allowed_origins: []
  flows: []
music:
  mode: provided # provided | library | search | generate
  path: assets/audio/track.mp3
features:
  beat_sync: required
  ui_3d: required
  ui_capture: required
edit:
  snap_tolerance_ms: 250
  focus_budget_per_scene: 1
  focus_scale: [1.20, 1.35]
approvals:
  mode: guided
output:
  resolution: 1920x1080
  fps: 30
  language: zh-TW
```

`record` needs non-empty declarative flows; `provided` needs media; `mixed`
needs at least one of them. A non-local base URL must appear in
`allowed_origins`. `approvals.mode: autonomous` additionally requires
`metadata.autonomous_authorization: true` and is still subject to hard safety
blockers.
