# AutoScene installation

AutoScene is distributed as a source checkout because its interface
includes pipeline YAML, Markdown director skills, JSON schemas, and the
Remotion workspace—not only importable Python packages.

## System prerequisites

| Requirement | Minimum | Recommended |
|---|---:|---:|
| Python | 3.12 | latest supported 3.12/3.13 patch |
| Node.js | 22 | current 22 LTS patch |
| npm | bundled with Node | current matching Node |
| FFmpeg + ffprobe | available on `PATH` | current stable build with H.264/AAC |

Official downloads: [Python](https://www.python.org/downloads/),
[Node.js](https://nodejs.org/), and [FFmpeg](https://ffmpeg.org/download.html).

Common system commands:

```bash
# macOS with Homebrew
brew install python@3.12 node@22 ffmpeg

# Ubuntu/Debian (Python/Node versions depend on your distribution)
sudo apt-get update
sudo apt-get install ffmpeg python3 python3-venv nodejs npm

# Windows PowerShell with winget
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Gyan.FFmpeg
```

Open a new terminal after installing system packages and confirm they are on
`PATH`.

## Clone-based setup

Use the clone URL shown on the GitHub repository page:

```bash
git clone https://github.com/Kuanyu458/AutoScene.git
cd AutoScene
python3 scripts/bootstrap.py
```

PowerShell:

```powershell
git clone https://github.com/Kuanyu458/AutoScene.git
cd AutoScene
py -3.12 scripts\bootstrap.py
```

Bootstrap performs only repository-scoped changes:

1. creates or reuses `.venv`;
2. installs the checkout in editable mode from `pyproject.toml`;
3. installs `remotion-composer/package-lock.json` with `npm ci`, using a cache
   inside the virtualenv so broken or privileged global npm caches cannot block setup;
4. copies `.env.example` only when `.env` does not exist;
5. runs `openmontage doctor` and returns nonzero on blockers.

To include development dependencies:

```bash
python3 scripts/bootstrap.py --dev
```

Inspect operations without writing:

```bash
python3 scripts/bootstrap.py --dry-run
```

## Doctor

```bash
.venv/bin/openmontage doctor
.venv/bin/openmontage doctor --json
```

PowerShell uses `.venv\Scripts\openmontage.exe`.

Doctor checks the source checkout, Python version and pinned DSP packages,
FFmpeg/ffprobe, Node/npm, pipeline loading, exact Remotion/Three/R3F package
versions, and the 3D source entry. It also reports Recordly as an optional
capture capability; a missing Recordly installation never blocks the Beat3D
runtime or ingestion of an already exported MP4. Doctor prints no environment
values.

## Optional providers

The Beat3D local path needs no API key. Copying `.env.example` creates empty
optional settings for cloud image/video/voice providers. Configure only the
providers you intend to use; provider-specific costs and data handling remain
separate approval decisions.

### Optional Recordly desktop recorder

Recordly is not installed by bootstrap and is not an OpenMontage dependency.
For polished real product UI capture, install it separately from the
[official Recordly releases](https://github.com/webadderallorg/Recordly/releases),
record and export an MP4 in its visible desktop UI, then give that exact path to
the `recordly_recorder` bridge. The bridge never searches the whole home folder
or relies on Recordly's private test interfaces. See
[RECORDLY_UI_CAPTURE.md](RECORDLY_UI_CAPTURE.md) for platform, privacy, and
license boundaries.

## Troubleshooting

- `SOURCE_CHECKOUT_NOT_FOUND`: run inside the clone or set
  `OPENMONTAGE_HOME=/absolute/path/to/clone`.
- `python_dependencies`: rerun bootstrap with Python 3.12+; do not reuse an old
  virtualenv created from an earlier requirements file.
- `remotion_three`: remove only `remotion-composer/node_modules` and rerun
  bootstrap so `npm ci` recreates the locked tree.
- H.264/AAC missing: install a full FFmpeg build for your platform.
- WebGL render failure: treat it as a blocker. Do not silently disable 3D or
  replace the approved runtime.

HyperFrames is optional for `auto-montage-3d` v1. Its availability does not
change the verified Remotion path and no live parity is claimed when it is
unavailable.
