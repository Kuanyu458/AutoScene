# Security policy

## Supported versions

Security fixes are accepted for the latest tagged beta and the current default
branch. Older snapshots may not receive backports.

## Reporting

Do not open a public issue containing credentials, private media, absolute user
paths, or unpublished project artifacts. Use GitHub's private security advisory
flow for the repository once it is published.

Include the affected version, operating system, reproduction steps, and the
smallest redacted log needed to diagnose the issue. Never attach `.env`, cloud
credential JSON, `projects/`, or user media.

## Local security model

- API keys stay in ignored `.env` files and are never printed by
  `openmontage doctor`.
- Source inputs are read-only; job staging copies and verifies hashes.
- The zero-key Beat3D renderer blocks remote assets.
- Bootstrap installs Python/npm dependencies from their public registries but
  never installs system packages or changes global credentials.
- Provider tools can send inputs to third-party APIs only after the user
  configures and approves that provider. The local Beat3D path does not require
  those calls.

Run `python scripts/check_public_tree.py` before every public release.
