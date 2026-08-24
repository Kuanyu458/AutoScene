# AutoScene

一套衍生自 OpenMontage agent-first 架構的 beta 工作流：自動剪輯素材、對準音樂
節拍／段落，並插入可重現的程序化 3D 動態場景。

[English](README.md) · [安裝說明](docs/INSTALLATION.md) ·
[完整 pipeline 契約](docs/AUTO_MONTAGE_3D.md) ·
[Recordly UI 錄製](docs/RECORDLY_UI_CAPTURE.md)

> macOS Apple Silicon 已通過真實 Remotion/WebGL 端到端測試。Linux 與 Windows
> 目前只宣稱安裝與契約層支援，不宣稱已完成 live 3D parity。

## 能做什麼

輸入一個整理好的資料夾，內含 brief、唯一一首音樂及影片／圖片素材；系統會：

1. 複製並 SHA-256 驗證輸入，不修改來源；
2. 只分析一次音樂，產生 deterministic `MusicTimingMap@1.0`；
3. 節拍不可靠時明確切換為 `phrase_flow`；
4. 依音樂 section 分配來源鏡頭與 3D 插入；
5. 預渲染 `ui-depth-stack`、`orbital-reveal` 或 `data-constellation`；
6. 建立以整數 frame 為權威、無 gap／overlap 的 TimelineV2；
7. 依核准的 runtime 合成並執行影音 QA。

這裡的 3D 是影片中的程序化全畫面動態場景，不是 GLB／GLTF 模型生成。

## 真實產品 UI 錄製

production `screen-demo` pipeline 現在可選用 Recordly 作為人工操作的 UI 錄製
後端：在 Recordly 錄製與美化後匯出 MP4，再由 `recordly_recorder` 對明確指定的
檔案執行唯讀複製、SHA-256、影音探測與可攜式封裝。AutoScene 不會內嵌或
自動安裝 Recordly，也不會修改來源；尚未解決的敏感 UI 會阻擋 publish。
FFmpeg、Cap 與 Playwright 仍是明確可選方案，既有自動選擇預設不變。詳見
[Recordly UI capture bridge](docs/RECORDLY_UI_CAPTURE.md)。

## 安裝

需求：Python 3.12+、FFmpeg/ffprobe、Node.js 22+、npm。

從 GitHub clone AutoScene：

```bash
git clone https://github.com/Kuanyu458/AutoScene.git
cd AutoScene
python3 scripts/bootstrap.py
.venv/bin/autoscene doctor
```

Windows PowerShell：

```powershell
git clone https://github.com/Kuanyu458/AutoScene.git
cd AutoScene
py -3.12 scripts\bootstrap.py
.venv\Scripts\autoscene.exe doctor
```

bootstrap 會建立隔離的 `.venv`、以 editable mode 安裝目前 source checkout、
執行 `npm ci`，並完成 fail-closed doctor。它不會安裝系統套件、不會覆寫既有
`.env`，也不會自動更換 renderer。

## 建立新工作

```text
my-materials/
├── brief.md
├── music.wav
└── media/
    ├── shot-01.mp4
    └── shot-02.mp4
```

```bash
.venv/bin/openmontage init /absolute/path/to/my-materials --slug launch-cut
```

系統會建立全新的 `projects/launch-cut/`、複製並驗證素材，遇到顯式 slug
衝突則停止，不覆寫既有 job。接著將 CLI 印出的提示貼給 Codex、Claude Code、
Cursor 等能讀檔與執行命令的 AI coding assistant：

```text
Use the auto-montage-3d pipeline. Read AGENT_GUIDE.md first, then continue
from projects/launch-cut/montage_request.json.
```

Python CLI 只負責安裝診斷與安全 staging；creative orchestration、proposal、
human checkpoint 與 stage review 仍由 agent 依 manifest/director skill 執行。

## 本地合成測試素材

```bash
python examples/auto-montage-3d/create_demo_inputs.py /tmp/openmontage-beat3d-demo
.venv/bin/openmontage init /tmp/openmontage-beat3d-demo --slug beat3d-demo
```

範例由 FFmpeg test source 與本地 120 BPM click track 生成，不需下載或提交
第三方影音。

## 驗證

```bash
make verify-release PYTHON=.venv/bin/python
```

真實 macOS E2E：

```bash
OPENMONTAGE_MACOS_E2E=1 .venv/bin/python -m pytest -q \
  tests/e2e/test_auto_montage_3d_macos.py
```

## 開源與第三方授權

本專案是 [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage)
的獨立衍生版，程式原始碼維持 [GNU AGPLv3](LICENSE)。AutoScene fork 保留上游
Git 歷史與 attribution，且不代表獲得上游維護者背書。

Remotion 使用獨立的 Remotion License；部分公司使用情境需要另購授權。Three.js
與 React Three Fiber 為 MIT。CutClaw 沒有被 vendor、import、執行或列為 dependency。
完整邊界請見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
安全 overrides 與 release audit 記錄於
[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md)。

使用者提供的素材、音樂、模型及輸出影片不會因放入本專案而被重新授權，也不應將
`projects/` 或含本機路徑的診斷 artifact 直接公開。
