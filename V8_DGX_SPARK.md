# V8_DGX_SPARK.md — 遷移到 DGX-SPARK（128 GB）的注意事項、待辦與 JS 改動

> 入口文件是 [`V8_README.md`](V8_README.md)；程式碼解說見 [`V8_CODEBASE.md`](V8_CODEBASE.md)。
> 本檔是**給工程師手動執行用的**：搬機器前要知道什麼、要照什麼順序做、
> **JavaScript／前端要改哪裡**。
> 最後更新：2026-08-31

---

## 0. 怎麼用這份文件

- **§1–§2** 先讀：現況、目標、以及「還沒解決就不准上線」的阻擋項。
- **§3** 是硬體與服務層的差異 —— 搬機器最容易踩雷的地方。
- **§4** 是可以照著打勾的執行清單。
- **§5** 是 **JavaScript／前端需要修改的部分**（含檔案路徑與判斷理由）。
- **§6–§8** 拓樸決策、驗收標準、回滾。

> ⚠ 本檔中凡標示 **【實機確認】** 的數字或行為，是依據 DGX-SPARK 公開規格與
> 一般 vLLM 經驗推論的，**必須在實機上量測後才能寫進正式文件**。
> 不要把推論值當成已驗證的事實往下傳。

---

## 1. 現況與目標

### 1.1 機器對照

| | 現在（開發／評估） | 未來（DGX-SPARK） |
|---|---|---|
| 機器 | 共用工作站，RTX PRO 6000 Blackwell **96 GB GDDR7** | **DGX-SPARK，128 GB 統一記憶體（LPDDR5X，CPU+GPU 共用）** |
| CPU 架構 | x86_64 | **ARM64（aarch64）** ⚠ |
| 記憶體性質 | 獨立顯存，頻寬約 1.8 TB/s | **統一記憶體，頻寬約 273 GB/s**【實機確認】 |
| 使用權 | **共用**（其他使用者也在跑東西） | **專屬** |
| vLLM 啟動 | 手動 `~/vllm-serve/serve.sh` | 應改為 **systemd 常駐** |
| 顯存配置 | `--gpu-memory-utilization 0.45`（約 44 GB，避免擠掉別人） | **要重新決定，語意也不同**（見 §3.2） |
| 介面 | Gradio 測試台 `:7862`（暫時） | **React SPA `:7861`（與 v6 相同）** |
| 引擎選擇 | `.env` 未設 → v6；手動改 `FHL_ENGINE=v8` 測試 | `.env` 設 `FHL_ENGINE=v8` |

### 1.2 目標

在 DGX-SPARK 上，讓使用者從 `tech.fhl.net/bible_bot/` 用**與現在完全相同的
React 介面**問問題，背後跑的是本地 Gemma，$0／查詢。
Gradio `:7862` 降級為內部除錯工具。

---

## 2. 上線前必須解決的阻擋項

**這五項在 `V8_README.md` §8 有背景說明。搬機器不會讓任何一項自動消失。**

### ☐ B1. 注入防護對「改寫過的攻擊句」仍不可靠 —— 最高優先

- 現況：正則（`gemma_bible_rag_v8.py` §3.2）只擋露骨句型；換句話說的攻擊
  仍依賴模型本身，而 Gemma 約 **1/3 會屈服**。
- 要做：
  1. 硬化 `BIBLE_SYSTEM_PROMPT` 的 Scope & Identity 區塊（**只改 v8 的副本**）。
  2. `adve01` (對抗攻擊測試01題)重跑 **≥10 次，要求 10/10 拒絕**。一次抽樣不算數。
  3. 題庫裡 `subtype=injection` 的 5 題全部要過，包含「夾在經文引文裡的指令」那題。
  4. 每次擴充正則後，**對 70 題全跑一次**，確認沒有誤殺正當提問
     （過度拒答在 `quant_eval.py` 有指標）。
- 驗收：`quant_eval.py` 的「declined when refusal was expected」= 100%、
  「over-refusal on legitimate questions」= 0%，且 `adve01` 10/10。

### ☐ B2. LLM judge 已評分 —— 而 v8 **沒有通過上線門檻**

2026-08-20 已用 `claude-opus-5` 對 v8／v6／v7／v4 各跑過同一份 50 題並排評分
（v8 的 judge 費用 $1.52）。所以問題不是「還沒評」，而是**評過而且沒過**。

> ⚠ **那次用的題庫是 `questions.private.json`（50 題，未去識別化，不在 GitHub 上）。
> 公開的 `questions.json`（70 題）從未評估過** —— 它雖沿用同一批 id，但 50 題中有
> **42 題的文字為了去識別化而改寫**，另外新增 20 題，且指標分母的定義也改了
> （改用 `expected_behavior` 欄位）。所以下表的數字**不能**直接當成公開題庫的成績。
> `questions.sample.json`（8 題）也從未評分過，只在 2026-08-20 15:57 對 v8 做過一次冒煙。
> 摘要已提交為 [`scripts/eval/report_20260820_judge.md`](scripts/eval/report_20260820_judge.md)。

| 指標（1–5，50 題平均） | v8 | v6 | 差距 | 上線門檻 |
|---|---:|---:|---:|---|
| faithfulness | 4.00 | 4.32 | **0.32** | ≤0.3 → ❌ 差一點 |
| relevancy | 4.40 | 4.94 | 0.54 | （非門檻項） |
| coverage | **3.50** | 4.58 | **1.08** | ≤0.3 → ❌ 大幅未過 |
| 中位延遲 | **2.60 s** | 25.85 s | — | v8 大勝 |
| 引擎成本 | **$0.00** | $1.53 | — | v8 大勝 |

**落差集中在哪裡**（逐類 F/R/C）：

| 類別 | v8 | v6 |
|---|---|---|
| adversarial (n=6) | **5.0 / 4.7 / 4.5** | 4.7 / 4.8 / 4.8 |
| exegesis (n=15) | 4.3 / 4.9 / 4.1 | 4.1 / 4.9 / 4.7 |
| contemporary (n=8) | 3.9 / 4.2 / 3.4 | 4.4 / 4.9 / 4.8 |
| doctrine (n=6) | 3.7 / 4.7 / 3.3 | 4.3 / 5.0 / 4.0 |
| figure_history (n=6) | 4.0 / 3.5 / **2.8** | 4.5 / 5.0 / 4.3 |
| synthesis (n=3) | 3.3 / 3.7 / **2.3** | 4.3 / 5.0 / 4.7 |
| word_study (n=6) | 3.2 / 4.0 / **2.7** | 4.2 / 5.0 / 4.7 |

- **對抗題反而是 v8 最強項**（5.0/4.7/4.5，優於 v6）—— 注入防護與品質閘有效。
- 崩壞集中在**需要多輪工具、跨經文綜合**的題型：word_study、synthesis、figure_history。
- 典型失敗（judge 逐題 rationale，**不只是「引用變少」**）：
  - `figu04` 問「推基古」，答成「提多」——人物張冠李戴，且未誠實說明查無資料；
  - `synt03` 把「得4:1」誤判為加拉太書並**捏造經文**；
  - `figu03` 問以斯拉記的 650 他連得，整篇談創世記約瑟屯糧——主題完全錯置；
  - `word02` **捏造 Strong's 編號** `SNHH2632`（正確為 H4960）。
- ⚠ 該次評分的 v8 run **已經包含**注入防護與品質閘（`adve01` 由 guard 直接攔下、
  另有 9 題觸發品質閘重試），所以這是「完整版 v8」的成績，不是半成品的成績。

**要做**：

1. 針對上述題型改 prompt（與 B3 是同一件事的兩面），用**免費**的 `quant_eval.py` 快速迭代；
2. 改完後對**公開的 70 題題庫（`questions.json`）重跑 v6 與 v8 的 judge 並排** ——
   這是**必做**，不是選配：現有的唯一一份 judge 成績是跑在
   `questions.private.json`（50 題）上的，而公開題庫的題目文字有 42 題被改寫過、
   另有 20 題全新，**兩者的數字不可直接並排**。若手上沒有 `questions.private.json`
   （它不在 GitHub 上），就更只能以公開題庫重建基線；
3. faithfulness 與 coverage 的差距都收斂到 ≤0.3 才可上線。
4. 若判斷差距收不了，正當的結論是**維持 v6 上線、v8 續留評估**——
   `GEMMA_VLLM_MIGRATION.md` §7 風險表第 2 項早就寫明「負面結果是可接受的結果」。

- 成本：引擎 v6 約 $1.5–3、v8 $0；judge 每版約 $2–4。
- ✅ 摘要已提交為 **`scripts/eval/report_20260820_judge.md`**（原始的
  `runs/report_20260820_v8.md` 在 gitignored 的 `runs/` 裡，新 clone 看不到）。
  另一份 `scripts/eval/report_20260821_quant.md` 是免費的確定性百分比評分。
- ⚠ `GEMMA_VLLM_MIGRATION.md` §9.7 寫「judge 從未跑過、門檻尚未量測」——
  那是撰寫當下（在一台沒有 `.env` 的機器上）的狀態，**當天稍晚就補跑了**。以本節為準。

### ☐ B3. 引用覆蓋率明顯比 v6 薄 —— 目前最實質的品質落差

50 題確定性評分（`scripts/eval/report_20260821_quant.md`）：

| 指標 | v8 | v6 |
|---|---|---|
| 引用有真實查詢佐證 | 74.8% | 89.4% |
| 每則答案引用數（平均） | 4.8 | 8.0 |
| 證據利用率 | 36.4% | 68.7% |
| **對共識集的引用召回率** | **52.5%** | **88.1%** |
| 每則答案引文數（平均） | 0.5 | 3.5 |

- 表徵是「連結少、引文少」而不是「答案錯」（連結有效性仍 100%）。
- 要做：prompt 層面加強「Cite as you write」與「完整引用 2–4 節」的遵循度，
  改完用 `quant_eval.py` 重測（**免費、離線，可以快速迭代**）。
- 建議目標：共識召回率提升到 **≥70%**，引文數 ≥2。

### ☐ B4. 內部工具名稱漏進答案文字

- 例：「…或 `get_word_analysis`？」。system prompt 已經有這條規則，Gemma 沒遵守。
- 要做：prompt 強化 ＋ 考慮在 `_postprocess_answer()` 加一道確定性清除
  （用 `TOOL_MAP.keys()` 生成正則）。**若採後者，記得同時處理「工具名剛好出現在
  程式碼區塊裡」的情況 —— 不過本 bot 本來就不該輸出程式碼，風險低。**

### ☐ B5. 沒有 systemd unit，vLLM 靠手動啟停

- 在專屬的 DGX-SPARK 上這是必須補的。範本見 §4.3。

---

## 3. 硬體與服務層的差異 —— 遷移最容易踩雷的地方

### 3.1 ⚠ ARM64（aarch64）—— **最大的技術風險**

現在的 vLLM venv（`~/vllm-serve/.venv`）是 x86_64 的 pip wheel。
DGX-SPARK 是 ARM64，**這些 wheel 一個都不能用**。

- `vllm`、`torch`、`flashinfer`、CUDA runtime 套件都要換成 aarch64 版本。
  很多套件的 aarch64 wheel 供應不如 x86 完整，最壞情況要**從源碼編譯**（很久）。
- **建議優先走 NVIDIA 官方容器**（`nvcr.io` 上的 vLLM／PyTorch NGC image），
  它們針對 GB10／DGX OS 預先建好，可以省掉大部分編譯地獄。
  用容器的話，`serve.sh` 就簡化成 `docker run …`／`podman run …`。
- **不管走哪條路，Phase 0 的驗收探針一定要重跑一次**
  （`GEMMA_VLLM_MIGRATION.md` §2.5）：純文字生成 → **tool calling** → 串流 tool calling。
  **tool calling 是整個 v8 的根基，換平台後必須重新證明它還在。**
- NVFP4 量化本身在 Blackwell 上是原生支援的；要確認的是 **flashinfer／vLLM 有沒有
  對應 DGX-SPARK 那顆 GPU 的 compute capability 建好 FP4 kernel**【實機確認】。
  第一次啟動的 JIT 編譯時間可能比現在的 195 秒更久，快取一樣落在 `~/.cache/flashinfer`。

### 3.2 ⚠ 統一記憶體 —— `--gpu-memory-utilization 0.45` 不能照抄

- DGX-SPARK 的 128 GB 是 **CPU 與 GPU 共用的一整塊**，不是獨立顯存。
  OS、bot 行程（FastAPI／Python）、以及任何其他工作都吃同一塊。
- `--gpu-memory-utilization` 的分母語意在統一記憶體平台上與獨顯不同【實機確認】，
  **不要直接沿用 0.45**。
- 建議做法：
  1. 先用保守值（例如 0.4–0.5）起得來再說；
  2. 用 `nvidia-smi` 與 `free -g` 同時觀察；
  3. 在確認 bot 行程與 OS 有足夠餘裕後，再往上調以換取更大的 KV cache。
- 模型權重才 15.3 GB，剩下都是 KV cache。**專屬機器的好處就是可以放大 KV cache**，
  進而支撐更高的並行度（見 §3.4）。

### 3.3 ⚠ 記憶體頻寬 —— 延遲一定會變，必須重新量測

- 解碼（decode）階段是**記憶體頻寬瓶頸**。DGX-SPARK 的 ~273 GB/s 對上
  RTX PRO 6000 的 ~1.8 TB/s，帳面差約 6–7 倍。
- **但這個模型是 MoE，每 token 只啟用約 4B 參數**（NVFP4 下每 token 大約只要讀
  2 GB 級的權重），所以退化幅度遠小於同尺寸的 dense 模型 ——
  這也正是當初選 26B-A4B 而不是 dense 模型的理由之一，對 Spark 反而是好事。
- **現有的「1.9–2.2 秒端到端」是 RTX PRO 6000 的數字，不可以直接寫進 Spark 的文件。**
  粗估 Spark 上會落在數秒等級【實機確認】，仍遠快於 v6 的 30–55 秒，但務必實測。
- 預填（prefill）是計算瓶頸而非頻寬瓶頸，Blackwell 的 FP4 算力充足，
  加上 vLLM 的自動 prefix caching 會重用共用的 system prompt 前綴，影響應該較小。
- 量測方式：`run_eval.py` 每題都會記錄延遲；跑一次 70 題，取中位數與 p95。

### 3.4 並行度

- `FHL_MAX_CONCURRENT`（預設 10）是 FastAPI 端的閘門，超過回 429。
- vLLM 端真正的限制是 KV cache 容量：`--max-model-len 32768` × 同時序列數。
  10 個並行的滿長度序列需要相當可觀的 KV cache。
- 要做：在 Spark 上實測「同時 N 個查詢」時的吞吐與記憶體，據以決定
  `--max-num-seqs` 與 `FHL_MAX_CONCURRENT`【實機確認】。
  真實流量的長度分佈遠短於 32768，不必用最壞情況估。

### 3.5 Python 版本與相依

- 本地開發機的 `.venv` 是 **Python 3.12**；正式伺服器（tech.fhl.net）的 venv 是
  **Python 3.9**。`requirements.txt` 標的是 3.9+。
- DGX-SPARK 上新建 venv 時請確認 `openai>=1.40.0` 與 fastapi/uvicorn 在該 Python
  版本 + aarch64 下都裝得起來。
- **bot 的 venv 與 vLLM 的 venv 必須維持分離**（`V8_README.md` §1）——
  bot 只需要 `openai` 這個薄 HTTP client，永遠不要把 vLLM 裝進 bot 的 venv。

### 3.6 `serve.sh` 要一起搬，而且要改寫

`~/vllm-serve/serve.sh` 在 **repo 外面**，git 不會幫你搬。它目前做三件事：

1. 設 `CUDA_HOME` 指向 venv 內的 nvcc；
2. 重建 pip CUDA 套件缺少的 unversioned soname symlink；
3. 用一串旗標啟動 `vllm serve`。

(1)(2) 是為了「系統沒有 CUDA toolkit、全靠 venv 裡那份」的 x86 環境而寫的。
**DGX OS 自帶完整 CUDA、或改用容器的話，這兩段可能完全不需要，甚至會幫倒忙。**
搬過去時請重新檢視，不要盲目複製。

必須保留的旗標（**少了任何一個 v8 就是壞的**）：

```
--enable-auto-tool-choice --tool-call-parser gemma4   # 整個 v8 的根基
--reasoning-parser gemma4                             # 少了它，thought 標記會漏進答案
--host 127.0.0.1                                      # 見 §6 安全
--served-model-name  <必須等於 .env 的 FHL_V8_MODEL_ID>
```

要重新決定的旗標：`--gpu-memory-utilization`（§3.2）、`--max-model-len`／
`--max-num-seqs`（§3.4）、`--port`（8010 只是為了避開共用工作站上的衝突，
在專屬機器上可以恢復 8000，但**改了就要同步改 `.env` 的 `FHL_V8_BASE_URL`**）。

---

## 4. 遷移執行清單

### 4.1 Phase A — 把模型服務起來（不碰 bot）

```
☐ A1. 確認 DGX-SPARK 的 OS、CUDA、Python、架構
       uname -m            # 應為 aarch64
       nvidia-smi          # 驅動與記憶體
       python3 -V
☐ A2. 下載模型 RedHatAI/gemma-4-26B-A4B-it-NVFP4（15.3 GB）
☐ A3. 建立獨立的 vLLM 環境（優先用 NVIDIA NGC 容器；否則獨立 venv）
       ※ 絕不要裝進 bot 的 venv
☐ A4. 改寫 serve.sh（§3.6），先用保守的 --gpu-memory-utilization 起起來
☐ A5. 等 "Application startup complete"（首次含 JIT 編譯，可能久於 195 秒）
☐ A6. 健康檢查： curl -s http://127.0.0.1:8010/v1/models
☐ A7. ★ 驗收探針（GEMMA_VLLM_MIGRATION.md §2.5）
       (a) 純文字生成
       (b) tool calling ← 最關鍵，沒過就停下來
       (c) 串流 tool calling
☐ A8. 記錄記憶體佔用與首 token 延遲基線
```

### 4.2 Phase B — 把 bot 接上去

```
☐ B1. clone repo、建 bot venv、pip install -r requirements.txt
☐ B2. 準備 .env：
        FHL_ENGINE=v8
        FHL_V8_BASE_URL=http://127.0.0.1:8010/v1      # 埠若改過要同步
        FHL_V8_MODEL_ID=<等於 --served-model-name>
        FHL_MAX_CONCURRENT=<依 §3.4 實測決定>
        # ANTHROPIC_API_KEY 仍建議保留 —— 回滾到 v6 與跑 judge 都要用
☐ B3. 直接呼叫引擎冒煙（不經過 FastAPI）：
        .venv/bin/python -c "import sys;sys.path.insert(0,'scripts');
        from gemma_bible_rag_v8 import bible_query;print(bible_query('約翰福音3:16的經文？'))"
☐ B4. 開 Gradio 測試台手動試（含 prompt injection 那題）
        .venv/bin/python scripts/app_v8.py
☐ B5. 建前端： cd web && npm ci && npm run build
☐ B6. 起 FastAPI： .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 7861
☐ B7. node e2e/verify-smoke.mjs                       # 17 項，免費
☐ B8. FHL_LOCAL_ENGINE=1 node e2e/verify-chat.mjs     # 15 項
☐ B9. 確認 usage_log 寫進 cost_usd = 0（不是 Sonnet 費率）
        sqlite3 logs/chat.db "select model, cost_usd from usage_log order by id desc limit 5;"
```

### 4.3 Phase C — 常駐化

```
☐ C1. 建立 vLLM 的 systemd unit（見下方範本），enable + start
☐ C2. 確認 bot 服務（fhl-bible-ui.service）在 vLLM 之後啟動、或能容忍 vLLM 尚未就緒
☐ C3. 重開機測試：整台重啟後兩個服務都能自己回來
☐ C4. 記錄「vLLM 冷啟動期間 bot 的行為」——
       目前會是連線錯誤 → SSE error 事件。確認前端訊息可接受（見 §5 J4）
```

`~/.config/systemd/user/vllm-gemma.service` 範本：

```ini
[Unit]
Description=vLLM serving Gemma 4 26B-A4B (NVFP4) for FHL bible bot
After=network-online.target

[Service]
Type=simple
ExecStart=%h/vllm-serve/serve.sh
Restart=on-failure
RestartSec=30
# 首次 JIT 編譯很久，不要讓 systemd 太早判定失敗
TimeoutStartSec=900
StandardOutput=append:%h/vllm-serve/server.log
StandardError=append:%h/vllm-serve/server.log

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now vllm-gemma.service
loginctl enable-linger $USER        # 登出後仍存活
```

### 4.4 Phase D — 品質關卡（不可跳過）

```
☐ D1. 對 70 題跑 v8： run_eval.py --engine v8
☐ D2. quant_eval.py（免費）——與 report_20260821_quant.md 的基準比較
☐ D3. judge_eval.py（付費）v6 vs v8 頭對頭 → report_eval.py 並排
☐ D4. §2 的 B1–B4 全部通過
☐ D5. 量測延遲中位數與 p95，更新 V8_README.md §1 的表（把 RTX 的數字換掉）
```

### 4.5 Phase E — 對外上線

```
☐ E1. 決定拓樸（§6）
☐ E2. nginx 設定（若對外路徑改變）
☐ E3. 灰度：先讓少數人用，看 logs/uvicorn_ui.log 與 usage_log
☐ E4. 準備好隨時回滾（§8）
☐ E5. 更新文件：V8_README.md、CODEBASE.md（頂層目錄、設定總覽、部署與回滾三張表）
```

---

## 5. JavaScript／前端需要修改的部分

### 5.0 ★ 先講最重要的一句話

> **不需要為了「讓 v8 跑起來」而改任何一行 JavaScript。**
> `.env` 寫 `FHL_ENGINE=v8` → 重啟 7861 → 現有的 React SPA 就在跑 v8 了。
> 因為 v8 和 v6 共用同一份 SSE 契約（`tool_log` / `text_delta` / `done` / `error`）、
> 同一份 API、同一份資料庫 schema。

以下 J1–J6 是「**因為引擎變成本地模型，所以呈現上應該調整**」的項目。
**J1、J2、J3 建議在對外上線前完成**；J4–J6 視情況。

---

### ☐ J1. 用量統計顯示 —— v8 的費用永遠是 $0.00，現在看起來像壞掉

**問題**：側欄的「用量統計」modal 顯示本月與累計費用。v8 的每一筆
`usage_log.cost_usd` 都正確地是 0，所以使用者／管理者會看到一整排 `$0.00`，
無法分辨「本地引擎所以免費」與「記帳壞掉」。

**建議做法**：讓 API 回報目前引擎，前端據以改變文案。

| 檔案 | 要做的事 |
|---|---|
| `server/chat.py` | `ENGINE` 已經是模組層變數（L48 附近），不必新增邏輯，只要能被讀到 |
| `server/sessions.py` | `/api/usage`（`get_usage`，L61 附近）的回應**新增**一個 `engine` 欄位，例如 `"v8"`；或在 `/api/health`（L56）一併回報 |
| `web/src/api/types.ts` | `UsageResponse` 介面加上 `engine?: string`（用選填，舊回應仍相容） |
| `web/src/components/Sidebar.tsx` | 用量 modal：`engine === "v8"` 時顯示「引擎：本地 Gemma 4 · 無 API 費用」，並把費用列標成 $0 或隱藏；其他引擎維持現狀 |

**注意**：`e2e/verify-smoke.mjs` 有一項在檢查 `/api/usage` 的結構
（month 標籤 + user/total × month/all_time）。**只新增欄位不會弄壞它**，
但若你改動既有欄位名稱就會 fail —— 只加不減。

---

### ☐ J2. 工具呼叫紀錄要顯示 v8 特有的兩種事件

**問題**：`web/src/components/ToolCallLog.tsx` 用 `line.includes("🔧")` 數工具呼叫數。
v8 的 tool log 多了兩種 v6 沒有的行：

```
[Guard] Prompt-injection pattern detected — refusing without LLM call
[Round 2] ⚠ Final-answer gate: no_tools (312 chars) — retrying (1 retry left)
```

注入防護觸發時**一個工具都不會呼叫**，所以現在會顯示「工具呼叫（0）」——
資訊完全沒有傳達出去。

**建議做法**：照抄 `scripts/app_v8.py` 的 `_format_log_block()`（L82–L93）的邏輯，
在 `ToolCallLog.tsx` 的標題列加兩個徽章：

```tsx
const guardFired = lines.some((l) => l.includes("[Guard]"));
const gateRetries = lines.filter((l) => l.includes("gate:")).length;
// 標題： 工具呼叫（N） · 🛡️ 安全防護已攔截 · ⚠ 品質重試 N 次
// guardFired 時，標題改為「已由安全防護攔截」而不是「工具呼叫（0）」
```

**不要為了前端好讀而去改引擎的 log 行格式** —— `e2e/verify-chat.mjs` 斷言
`tool_log` 有被持久化，而歷史對話的 `messages.tool_log` 也是既有格式，
改格式等於讓舊資料顯示不一致。要美化就在前端做。

**順帶一提**：v8 的工具參數在 log 裡是 **JSON 字串**（v6 是 Python dict 的字串形式），
所以 `🔧 get_bible_verse({"book": "約翰福音", "chapter": 3, "verse": 16})` 讀起來
略有不同。要美化也是在前端 parse，不要動引擎。

---

### ☐ J3. 逾時設定目前是矛盾的 —— nginx 300s vs 引擎 600s

**問題**：

| 層 | 逾時 | 位置 |
|---|---|---|
| nginx | `proxy_read_timeout 300s` | `nginx-bible_bot-snippet.conf` |
| 引擎 → vLLM | `timeout=600.0` | `gemma_bible_rag_v8.py` 的 `_get_client()` |
| 前端 | 無自訂逾時（靠 `AbortController` 由使用者手動停止） | `useConversation.ts` / `chatStream.ts` |

也就是說：一個跑超過 300 秒的查詢，**nginx 會先切斷連線**，前端拿到的是連線中斷
而不是清楚的錯誤訊息，而後端的 worker thread 還會繼續跑到完（存檔仍會成功）。

**要做**：在 Spark 上量測最壞情況（10 輪工具鏈 + comprehensive 風格）的耗時後，
二選一：
- 若最壞情況明顯 < 300s → 把引擎的 client timeout 調到小於 nginx 的值，
  讓逾時錯誤由引擎產生、能走 SSE `error` 事件傳給前端；
- 若可能接近或超過 300s → 調高 nginx 的 `proxy_read_timeout`／`proxy_send_timeout`
  （**nginx 設定需要伺服器管理員**）。

前端可選的改善：在 `useConversation.ts` 加一個「超過 N 秒仍無任何 delta」的
提示文字，而不是讓使用者對著 ⏳ 乾等。

---

### ☐ J4. vLLM 尚未就緒時的錯誤訊息

**問題**：vLLM 冷啟動要數分鐘。這期間任何查詢都會拿到
`APIConnectionError: Connection refused`，經由 SSE `error` 事件原樣顯示給使用者
——一般使用者看不懂。

**建議**：
- 後端（`server/chat.py` 的 except 區塊）把連線類錯誤轉成中文的友善訊息，
  例如「AI 服務啟動中，請稍候約一分鐘後再試」；
- 或前端 `chatStream.ts` 的 `onError` 對特定關鍵字做映射（**已有 429 的先例**：
  `chatStream.ts` 對 429 回「目前使用人數較多，請稍後再試。」，照同一個模式做即可）。

後端做比較好：訊息只有一份，Gradio 測試台與 API 直接呼叫者也一起受惠。

---

### ☐ J5. e2e 腳本（也是 JS）

- `e2e/verify-chat.mjs` 在 v8 底下**必須**加環境變數，否則 `cost > 0` 斷言必 fail：

  ```bash
  FHL_LOCAL_ENGINE=1 node e2e/verify-chat.mjs
  ```

- `deploy.sh` 目前只跑 `verify-smoke.mjs`（免費），**不受影響**。
  若要在部署流程裡加上 chat 驗證，記得帶上該環境變數。
- `e2e/verify-smoke.mjs` 完全不需要改。

---

### ☐ J6. 建置與路徑（只有在對外路徑改變時才需要）

前端的 base path 目前是 `/bible_bot/`，**三個地方必須一致**：

| 位置 | 設定 |
|---|---|
| `web/vite.config.ts` | `base: "/bible_bot/"` 以及 dev proxy 的 rewrite |
| `server/main.py` | router 的 `prefix="/bible_bot"` 與 StaticFiles 的 mount 路徑 |
| `nginx-bible_bot-snippet.conf` | `location /bible_bot/` 與 `/bible_bot/api/` |

若 DGX-SPARK 上的公開路徑不同，這三處要一起改，然後 `npm run build`。
**nginx 的 `proxy_buffering off;` 絕對不能拿掉 —— SSE 串流靠它。**

建置指令（前端有改動時）：

```bash
cd web && npm ci && npm run build     # 產物在 web/dist，FastAPI 直接服務，不需重啟後端
```

---

### 5.7 明確**不需要**改的前端檔案

避免接手的人「順手重構」：

| 檔案 | 為什麼不用改 |
|---|---|
| `src/api/chatStream.ts` | SSE 契約沒變（除非做 J4） |
| `src/hooks/useConversation.ts` | 串流／中止邏輯與引擎無關（除非做 J3 的提示） |
| `src/lib/liveStreams.ts` | 切換對話不中斷串流，與引擎無關 |
| `src/lib/verseLinks.ts` | 連結由後端 Python 生成，格式一模一樣 |
| `src/components/ChatMessage.tsx` | markdown 渲染與 href 改寫，與引擎無關 |
| `src/components/ChatInput.tsx` | IME 保護、風格切換 —— `brief`/`comprehensive` 兩種風格 v8 同樣支援 |
| `src/App.tsx` | 版面與設定持久化 |

---

## 6. 拓樸決策（上線前必須拍板）

目前正式服務跑在 **tech.fhl.net**，GPU 在**另一台機器**。DGX-SPARK 到位後有兩條路：

### 選項 A — bot 與 vLLM 同機（**推薦**）

FastAPI 與 vLLM 都跑在 DGX-SPARK 上，`FHL_V8_BASE_URL` 維持 `127.0.0.1:8010`。

- ✅ 最簡單、零網路安全面、延遲最低、**不需要改任何連線設定**。
- ⚠ 需要 DGX-SPARK 能被 nginx 反向代理到（可能是把 nginx 也放上去，
  或由 tech.fhl.net 的 nginx 往內網代理 7861 —— **只代理 7861，永遠不要代理 8010**）。
- ⚠ DGX-SPARK 的可用性等同於服務的可用性。

### 選項 B — bot 在 tech.fhl.net，vLLM 在 DGX-SPARK（跨機）

`FHL_V8_BASE_URL` 指向另一台機器。

- ⚠ **vLLM 絕對不可以直接 bind 到 0.0.0.0 或對外網開放** ——
  它沒有認證、沒有速率限制，等於把一台 GPU 免費送人用。
  必須走 **SSH tunnel 或 VPN（WireGuard 之類）**，vLLM 本身維持 `--host 127.0.0.1`。
- ⚠ 要處理：tunnel 斷線重連、跨機延遲、逾時、以及「網路不通時 bot 的行為」。
- ⚠ 兩台機器都要有 `.env`，且引擎設定要一致。

**未決問題（`GEMMA_VLLM_MIGRATION.md` §6 提出，至今無答案）**：
誰負責 vLLM 的 uptime？機器重開時 in-flight 的查詢怎麼辦？
出口連線的防火牆規則允許嗎？**這些是人的決策，不是技術問題，要先問清楚。**

---

## 7. 驗收標準（全部通過才算遷移完成）

```
☐ vLLM 在 DGX-SPARK 上穩定服務，systemd 常駐，重開機能自動回來
☐ tool calling 探針三項全過
☐ node e2e/verify-smoke.mjs                     → 17/17
☐ FHL_LOCAL_ENGINE=1 node e2e/verify-chat.mjs   → 15/15
☐ adve01 注入題 10 次全部拒絕
☐ quant_eval：拒答率 100%、過度拒答 0%、簡體 0%、連結有效性 100%
☐ quant_eval：共識引用召回率達到與 v6 的差距目標（B3）
☐ judge_eval：faithfulness 與 coverage 與 v6 差距 ≤ 0.3
     （2026-08-20 基線：faithfulness 差 0.32、coverage 差 1.08 —— 兩項都還沒過）
☐ 延遲中位數與 p95 已量測並寫進 V8_README.md
☐ React SPA（7861）能正常對話，工具紀錄、經文連結、用量統計都正確
☐ usage_log 的 v8 紀錄 cost_usd = 0，model 欄位是真實 model id
☐ 回滾演練做過一次（見 §8）
```

---

## 8. 回滾

**任何時刻都能一行回滾。**

```bash
# .env
FHL_ENGINE=v6          # 或直接刪掉這一行（未設 → v6）
```

```bash
systemctl --user restart fhl-bible-ui.service
curl -s 127.0.0.1:7861/bible_bot/api/health     # → {"status":"ok"}
node e2e/verify-smoke.mjs
```

前提條件（**上線前請確認這兩件事都成立**）：
- `.env` 裡的 `ANTHROPIC_API_KEY` 還在且有效；
- bot 的 venv 裡 `anthropic` 套件還在（`requirements.txt` 從未移除它）。

Sonnet 的計價常數也從未移除，`_estimate_cost_usd()` 的 `gemma-` → $0 防護
對歷史資料無害 —— 回滾後新的查詢會恢復正常計費。

**上線前務必實地演練一次回滾**，不要等到出事才第一次做。
