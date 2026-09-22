# Source-led editing 與 revisioned timeline

本文件記錄本次導入的兩類能力：以 `video-use` 為靈感的素材理解／剪輯查核，以及以
`openvid` 為靈感的時間軸編輯介面。實作採用 OpenMontage 原生的
`BaseTool`、pipeline、artifact schema 與 Backlot 架構；沒有複製或 vendoring 任一上游
專案的程式碼、資產或瀏覽器 runtime。

## 導入範圍與必要性

| 參考能力 | AutoScene 對應實作 | 導入判斷 |
|---|---|---|
| `video-use`：逐字稿驅動剪輯、來源時間軸檢視、剪輯邊界查核 | `editorial_transcript`、`timeline_inspector`、`cut_boundary_qa` | 對 `talking-head`、`clip-factory`、`podcast-repurpose`、`hybrid`、`screen-demo` 與 `openmontage-video` 等素材導向流程建議啟用；純生成式流程可不使用。 |
| `openvid`：可視化時間軸、trim／reorder、焦點縮放 | `edit_timeline` artifact、`/p/<project_id>/edit`、`/api/project/{project_id}/edit-timeline`、Remotion zoom keyframes | 適合需要人工微調剪輯的產品影片；屬於選用的 authoring layer，不取代既有 pipeline 或 native renderer。 |
| `openvid`：瀏覽器 `getDisplayMedia`、webcam／microphone 即時錄製、多軌 realtime capture、GLB mockup | 不直接導入；保留既有 Playwright recorder 與 HyperFrames／Three.js／Blender 路徑 | 這些能力會改變 AutoScene 的權限、媒體生命週期與渲染架構，暫不以外部專案 runtime 取代現有治理契約。 |

核心原則是「分析與編輯可並行，渲染仍走既有管線」：時間軸只描述可稽核的編輯意圖，
不在瀏覽器中偷偷產生另一份影片。

## 工作流程

```text
source footage / recording
        │
        ├─ transcriber output (Whisper/WhisperX-compatible JSON)
        │       └─ editorial_transcript.json
        │                ├─ words + phrases + silence/audio events
        │                └─ source fingerprint + cache key
        │
        ├─ edit agent writes edit_decisions.json
        │       └─ cut_boundary_qa → cut_review.json (+ optional evidence PNG)
        │
        └─ normalize → edit_timeline.json (revisioned authoring contract)
                        ├─ Backlot /p/<project_id>/edit
                        ├─ GET/PATCH edit-timeline API
                        └─ video_compose → edit_decisions → Remotion/HyperFrames/FFmpeg
```

以上工具都是 registry-discovered `BaseTool`。在 pipeline 中它們是 optional tools；沒有
逐字稿、素材路徑或相應 runtime 時，既有流程仍可照原本的 artifact contract 執行，
但不應宣稱已完成逐字稿或邊界證據查核。

## Canonical artifacts

所有 JSON 產物都必須寫入 `projects/<project_id>/artifacts/` 並通過
`schemas/artifacts/` 驗證。

| Artifact | 檔案 | 內容與用途 |
|---|---|---|
| `editorial_transcript` | `editorial_transcript.json` | 正規化的 word-level timestamps、phrase groups、speaker／source metadata、silence／audio events、來源 fingerprint 與 cache key。 |
| `cut_review` | `cut_review.json` | 每個相鄰 hard cut 的 `pass`／`warn`／`fail`、`split_word` 與 `insufficient_padding` 問題、coverage summary，以及可選的 `timeline_inspection` 證據圖。 |
| `edit_timeline` | `edit_timeline.json` | 共享的 authoring contract：`revision`、sources、segments、zoom keyframes、audio tracks、overlays 與 renderer metadata。 |
| `timeline_inspection` | `timeline_inspection.json`（PNG 同名 sidecar） | 指定來源區間的 filmstrip、waveform、word labels、silence bands 與持久化 frame evidence。 |
| `edit_decisions` | `edit_decisions.json` | 既有 canonical renderer input；現在可選擇包含 `zoom_keyframes`。轉換時會保留字幕、音訊、overlay、bespoke 與 automation 欄位。 |

### `editorial_transcript` 最小輸入

工具接受既有 transcriber 的常見形狀，不綁定單一 ASR provider：

```json
{
  "provider": "whisperx",
  "language": "zh",
  "word_timestamps": [
    {"start": 0.00, "end": 0.42, "word": "這是"},
    {"start": 0.46, "end": 0.95, "word": "產品示範。"}
  ]
}
```

工具會依 silence gap、speaker／source 變更與 phrase word 上限分組；CJK 和標點不會被
錯誤插入英文空格。若提供 `source_path`，fingerprint 以來源檔案 SHA-256 為準；否則
以 transcript payload hash，避免不同來源誤用同一份快取。

### `edit_timeline` 操作

`lib/edit_timeline.py` 只處理純資料，不包含瀏覽器或渲染程式。支援的操作固定為：

- `trim`：更新單一 segment 的 `source_in_seconds`／`source_out_seconds`，並重新計算
  後續 timeline positions。
- `reorder`：以完整且不重複的 `segment_ids` 重新排序。
- `set_zoom_keyframe`：設定 segment 內的時間、scale、`x`／`y` focus 與 easing。
- `remove_zoom_keyframe`：移除 segment／time 對應的 focus keyframe。

未知操作會 fail closed；每次成功更新都遞增 `revision`。這讓 Agent、Backlot tab 與審核
工具可以用同一份資料交換編輯意圖，而不是依賴不可重現的 DOM state。

## Backlot 編輯器與 API

先依一般專案規範啟動 Backlot：

```bash
python -m backlot open <project_id>
```

若專案已有 `edit_decisions.json`，首次請求會 lazy-normalize 成 revision `0` 的
`edit_timeline`；之後 PATCH 會以 atomic replace 寫入
`projects/<project_id>/artifacts/edit_timeline.json`。編輯頁面位於：

```text
/p/<project_id>/edit
```

### 讀取時間軸

```http
GET /api/project/{project_id}/edit-timeline
```

### 套用編輯

```http
PATCH /api/project/{project_id}/edit-timeline
Content-Type: application/json

{
  "base_revision": 0,
  "operations": [
    {
      "op": "trim",
      "segment_id": "cut-0000",
      "source_in_seconds": 0.25,
      "source_out_seconds": 4.50
    },
    {
      "op": "set_zoom_keyframe",
      "segment_id": "cut-0000",
      "time_seconds": 1.20,
      "scale": 1.25,
      "x": 0.50,
      "y": 0.42,
      "easing": "ease-in-out"
    }
  ]
}
```

API 以 process-level lock 包住讀取、revision check 與 atomic replace：

- `200`：回傳新 timeline 與遞增後的 revision。
- `409`：`base_revision` 過期；前端必須重新讀取並由使用者／Agent 解決衝突。
- `400`：payload 不完整、segment 不存在或操作不受支援。
- `404`：專案沒有 `edit_timeline.json` 或 legacy `edit_decisions.json`。

Board 的 state／SSE 仍然是觀察面；只有這組明確的 edit-timeline API 具有寫入權限。

## 渲染相容性

`tools/video/video_compose.py` 同時接受 `edit_decisions` 或 `edit_timeline`。傳入 timeline
時先透過 `timeline_to_edit_decisions()` 還原既有 renderer input，再依提案鎖定的
`render_runtime` 執行：

| Runtime | `zoom_keyframes` 行為 |
|---|---|
| `remotion` | 已支援 scale、focus origin 與 easing；每個 cut 只套用對應 `segment_id` 的 keyframes。 |
| `ffmpeg` | 若存在 zoom keyframes 會明確阻擋，要求改用 Remotion 或移除 keyframes；不會靜默遺失編輯。 |
| `hyperframes`（stock adapter） | 目前尚未消費 zoom keyframes，同樣明確阻擋；HyperFrames atelier 若要支援，需另行擴充其 authoring contract。 |

`edit_timeline.metadata.base_edit_decisions` 會保留 renderer-only fields，因此從 Backlot
保存 timeline 不會丟失字幕、音訊、overlays、bespoke 或 automation evidence。

## Pipeline 啟用範圍

下列 footage-led manifests 已將分析／QA／timeline inspection 宣告為 optional tools：

- `pipeline_defs/talking-head.yaml`
- `pipeline_defs/clip-factory.yaml`
- `pipeline_defs/podcast-repurpose.yaml`
- `pipeline_defs/hybrid.yaml`
- `pipeline_defs/screen-demo.yaml`
- `pipeline_defs/openmontage-video.yaml`

這是相容性設計：既有專案不需要重新產生 artifact 才能繼續；當素材導向流程要宣稱
「逐字稿可編輯」或「每個 cut 已查核」時，應在 edit stage 實際產出對應 artifact，並把
warnings／evidence_error 帶入 review。

## 建議的導入決策

- **必須可稽核地剪長素材／訪談／Podcast：** 啟用 `editorial_transcript` +
  `cut_boundary_qa`，並在有來源檔案時產生 `timeline_inspection` 證據。
- **需要人機協作微調：** 在 Backlot 使用 `edit_timeline`；先 trim／reorder，再提交
  zoom keyframes，最後讓 native renderer 產生預覽或正式輸出。
- **只有生成式場景、沒有 source footage：** 不需要這組工具；維持既有
  `edit_decisions`／scene-based composition 即可。
- **需要 webcam／mic 或瀏覽器即時捕捉：** 目前沿用既有 Playwright recorder／外部錄製
  匯入，不把 `openvid` 的非同步瀏覽器 capture runtime 直接併入 pipeline。

## 測試

執行本次功能的 focused tests：

```bash
python -m pytest -q \
  tests/tools/test_editorial_editing.py \
  tests/tools/test_edit_timeline_renderer.py \
  tests/tools/test_timeline_inspector.py \
  tests/tools/test_cut_evidence_contract.py \
  tests/backlot/test_edit_api.py \
  tests/backlot/test_editor_page.py \
  tests/lib/test_source_media_review_compat.py
```

也應執行 pipeline catalog／phase contract tests，確認 optional tool 宣告與 artifact
catalog 沒有破壞既有流程：

```bash
python -m pytest -q \
  tests/contracts/test_pipeline_catalog.py \
  tests/contracts/test_phase1_contracts.py \
  tests/backlot/test_ui_bug_bash.py
```

## 授權與再散布

本 repository 仍以 [AGPLv3](../LICENSE) 發布。此次實作沒有將兩個參考 repository 的
程式碼或資產複製進來：

- [`browser-use/video-use`](https://github.com/browser-use/video-use) 的 MIT 授權只適用於其
  上游專案；本實作只採用功能層面的設計參考。
- [`CristianOlivera1/openvid`](https://github.com/CristianOlivera1/openvid) 使用
  PolyForm Noncommercial 1.0.0 source-available 授權，並非 OSI open-source license；
  本專案沒有 vendoring 其程式碼。若未來要直接整合、再散布或商用，必須先完成授權與
  法務審查，不能依本 repository 的 AGPLv3 推定取得 OpenVid 權利。

第三方 runtime／套件請一併查看 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
