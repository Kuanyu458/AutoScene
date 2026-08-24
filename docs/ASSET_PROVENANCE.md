# Asset provenance policy

AutoScene source, runtime dependencies, user media, and generated output are
four different licensing domains. Do not collapse them into one license claim.

## Public source tree

- `assets/` and the inherited `.agents/skills/` tree originate from the
  upstream OpenMontage distribution unless a closer provenance file says
  otherwise.
- This derivative preserves upstream Git history and documents its source-delta
  base plus integration target in `UPSTREAM.md`.
- Root demonstration media is not required by `auto-montage-3d`. New Beat3D
  examples must be generated locally through
  `examples/auto-montage-3d/create_demo_inputs.py` instead of adding media.

The public-tree gate recognizes these unchanged upstream large assets by exact
SHA-256 so replacements cannot enter silently:

| Path | SHA-256 |
|---|---|
| `.agents/skills/hyperframes-animation/examples/assets/hyperframes-showcase-hypecard.mp4` | `59894d108c5634cce855f4b9593d48ee0884955b1607e0f1c1c4e973e2eb101e` |
| `.agents/skills/hyperframes-animation/examples/assets/background-tech-data-flow.mp4` | `f5d7c64dffda80b3b15bd116e4f2fda2231ae5d7997f2753ba01051aa243ce79` |
| `assets/signal-from-tomorrow-demo.mp4` | `47d46d729e0881d37ea87e49a0d1cfb8277434bb58d66e0d51ac5163fd020dac` |

Their presence is inherited-source provenance, not a new Beat3D licensing
claim. A maintainer may remove them from a focused release after confirming no
remaining upstream documentation depends on them.

## New vendored material

Before adding any image, video, audio, model, font, shader, JavaScript bundle,
skill pack, or template, record:

```text
Path:
Source URL:
Version or commit:
Author/copyright holder:
License:
Redistribution allowed: yes/no/unclear
Modifications:
Required attribution:
```

`unclear` means the file does not enter the public tree.

## Local and generated material

- `projects/`, `music_library/`, `.env`, model downloads, caches, renders, and
  QA outputs are ignored and never part of a release.
- `MontageRequest` retains original absolute paths for provenance; publishable
  diagnostics must redact them.
- ThreeScenePackage also records project-relative paths so a job archive can be
  moved and verified without depending on the old absolute render path.
