# Dependency security audit

Last reviewed: 2026-08-24

The Remotion family remains locked at `4.0.484` because renderer packages must
move together and this beta has perceptual and real-render acceptance evidence
against that version.

The upstream Remotion bundler dependency tree originally resolved vulnerable
patch versions of `fast-uri`, `nanoid`, and `postcss`. The composer therefore
uses exact npm `overrides` for patched releases within the same major versions:

| Transitive package | Reviewed override | Reason |
|---|---:|---|
| `fast-uri` | 3.1.5 | exact direct pin reused as the transitive override |
| `nanoid` | 3.3.18 | non-secure generator loop advisories in earlier 3.x patches |
| `postcss` | 8.5.25 | patched release retained by the exact composer override |

Release verification requires all of the following after regenerating the npm
lockfile:

```bash
npm ci --prefix remotion-composer --no-audit --no-fund
npm audit --prefix remotion-composer --omit=dev --audit-level=high
npm run typecheck --prefix remotion-composer
```

The override set is accepted only while TypeScript checks, Remotion composition
loading, the complete Python contract suite, and the macOS Apple Silicon real
render E2E all pass. Do not use `npm audit fix --force`: it may upgrade the
Remotion family independently and break the renderer contract.
