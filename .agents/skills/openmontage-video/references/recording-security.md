# Recording and import safety

`playwright_recorder` runs Node 22 Playwright 1.62.1 in a fresh context at
1920×1080 by default. The flow vocabulary is deliberately small and is
validated before the browser opens. Selectors are ordinary Playwright
selectors; values are visible, non-secret UI values only.

The base origin must be localhost (`localhost`, `127.0.0.1`, or `::1`) or be
explicitly listed. Every `goto` is checked against that allow-list. Credentials,
cookies, storage state, login steps, arbitrary JavaScript/shell, external
redirects, and cross-origin iframe flows are rejected. Screenshots and
recordings stay under the project assets directory; the runner emits a hash,
interaction log, focus map, contact sheet, and privacy report.

The runner's only page script is fixed, project-owned cursor/click-ripple
instrumentation. A job cannot inject, select, or alter JavaScript.

Recordly is supported as an import boundary only: provide its exported MP4 or
WebM and review it like any other supplied media. Do not depend on `.recordly`
internals or infer a headless CLI that the public project does not document.
