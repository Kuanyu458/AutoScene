# Security policy

## Scope

Security issues in OpenMontage or the `$openmontage-video` skill include
credential leakage, cross-origin recording, arbitrary command/JavaScript
execution through a job, privacy-report bypass, and silent runtime or feature
downgrades.

## Safe recording contract

- Jobs must not contain passwords, API keys, cookies, storage state, or bearer
  tokens.
- Browser capture uses a fresh context and only localhost or explicitly
  allow-listed origins.
- The supported flow vocabulary is limited to navigation, click, fill, select,
  press, scroll, wait, assert, hold, and screenshot.
- Native desktop capture is imported as user-provided Recordly/Cap MP4 or WebM;
  the agent does not automate a login or desktop session.
- Rights, privacy, credentials, and runtime checks are artifacts and remain
  blocking until the appropriate gate is approved.

## Reporting

Please report a suspected vulnerability privately to the project maintainers
before opening a public issue. Include the smallest reproducible job and omit
all credentials or private media. Do not attach storage-state files, cookies,
medical documents, or user recordings.

## Release checks

Every release should run the license scan, SBOM generation, dependency lock
verification, job secret tests, origin-allow-list tests, and a localhost-only
recording smoke test.
