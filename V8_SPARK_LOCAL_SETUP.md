# V8_SPARK_LOCAL_SETUP.md — 在 DGX Spark 上跑 v8 bot（共用現有 vLLM）

> 最後更新：2026-11-08　·　已在 `spark-1b8c` 實機驗證
> 背景與上線門檻見 [`V8_DGX_SPARK.md`](V8_DGX_SPARK.md)；本檔只講「怎麼跑起來」。

---

## 1. 架構一句話

這台機器上**已經有一個 vLLM container 在跑**（port `8000`，Gemma 4 26B-A4B，
已開 tool calling）。bot 不需要自己的 vLLM —— 只要建 Python venv、build 前端、
`.env` 指向 `127.0.0.1:8000` 即可。

```
Browser ──► bot (FastAPI + React SPA, :7861 或自訂 port) ──► vLLM container (:8000)
```

## 2. 機器現況

| 項目 | 值 |
|---|---|
| 硬體 | NVIDIA DGX Spark，GB10（compute capability 12.1） |
| CPU 架構 | **ARM64（aarch64）**，20 核 |
| 記憶體 | 128 GB unified memory（CPU / GPU 共用）；vLLM 佔約 110 GB |
| OS / CUDA | Ubuntu 24.04、driver 580、CUDA 13.0 |
| Python | 3.12（系統內建） |
| Node | 系統是 **18** —— **不夠用**，前端需要 ≥ 20（見 §4） |

vLLM container 的重點參數（`docker` 由 root 啟動）：

```
vllm serve --model=google/gemma-4-26B-A4B-it
  --enable-auto-tool-choice --tool-call-parser=gemma4 --reasoning-parser=gemma4
  --kv-cache-dtype=fp8 --max-model-len=262144 --max-num-seqs=4
  --enable-chunked-prefill --enable-prefix-caching
```

注意兩點：
- Model 是 **BF16 原版**（不是 RTX 上測的 NVFP4），served model id 是
  `google/gemma-4-26B-A4B-it`。
- `--max-num-seqs=4` → vLLM 同時最多處理 4 個序列，所以 `FHL_MAX_CONCURRENT=4`。

## 3. 先確認 vLLM 活著

```bash
curl -s http://127.0.0.1:8000/v1/models
# 應看到 "id":"google/gemma-4-26B-A4B-it"
```

## 4. 安裝 Node 24（不需要 sudo）

Tailwind 的 native module（`@tailwindcss/oxide`）要求 Node ≥ 20。
用 Node 18 會出現 `Cannot find native binding`。裝在自己的 home 底下：

```bash
V=v24.22.2
mkdir -p ~/.local/opt && cd ~/.local/opt
curl -LO https://nodejs.org/dist/$V/node-$V-linux-arm64.tar.xz
tar xf node-$V-linux-arm64.tar.xz && rm node-$V-linux-arm64.tar.xz
ln -sfn node-$V-linux-arm64 node24
export PATH=$HOME/.local/opt/node24/bin:$PATH     # 建議加進 ~/.bashrc
node --version                                     # → v24.x
```

## 5. 安裝 bot

在 repo 根目錄：

```bash
# 5.1 Python venv（與 vLLM 完全分開）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 5.2 前端
cd web && npm ci && npm run build && cd ..      # 產物在 web/dist
```

### 5.3 `.env`

```ini
FHL_ENGINE=v8
FHL_V8_BASE_URL=http://127.0.0.1:8000/v1
FHL_V8_MODEL_ID=google/gemma-4-26B-A4B-it
FHL_MAX_CONCURRENT=4
# ANTHROPIC_API_KEY=...   # 選填：回滾到 v6 或跑 judge eval 才需要
```

- `/v1` 是 vLLM 的 OpenAI-compatible API 網址路徑，不是資料夾。
- `FHL_V8_MODEL_ID` **必須**完全等於 `/v1/models` 回傳的 `id`（見 §3 的 `curl`）。
  名稱不符時 vLLM 會拒絕：
  `The model 'gemma-4-26B-A4B-it-NVFP4' does not exist.`（404）
- `FHL_ENGINE=v8.1` 也可以，設定相同。
- `.env` 已在 `.gitignore`，不要 commit。

## 6. 啟動

```bash
# 引擎直接冒煙（不經 FastAPI），約 6 秒
.venv/bin/python -c "import sys;sys.path.insert(0,'scripts')
from gemma_bible_rag_v8 import bible_query;print(bible_query('約翰福音3:16的經文？'))"

# 起 bot（背景執行）
mkdir -p logs
setsid nohup .venv/bin/python -m uvicorn server.main:app \
  --host 127.0.0.1 --port 7861 > logs/uvicorn_ui.log 2>&1 < /dev/null &

curl -s http://127.0.0.1:7861/bible_bot/api/health     # → {"status":"ok"}
```

瀏覽器開 `http://127.0.0.1:7861/bible_bot/`（遠端可用 VS Code port forwarding
或 `ssh -L 7861:127.0.0.1:7861 <host>`）。

> **Port 衝突**：同一台機器上若已有別人的 bot 佔用 7861，改用其他 port（例如 `7871`），
> 下面測試的 `BASE_URL` 也要一起改。

停止：

```bash
pgrep -af "uvicorn server.main:app"     # 找 PID
kill <PID>
```

## 7. 測試

```bash
export PATH=$HOME/.local/opt/node24/bin:$PATH
BASE=http://127.0.0.1:7861/bible_bot

BASE_URL=$BASE node e2e/verify-smoke.mjs                      # 免費，17 項
BASE_URL=$BASE FHL_LOCAL_ENGINE=1 node e2e/verify-chat.mjs    # 本地 model，$0

# 確認 v8 的費用記為 0
sqlite3 logs/chat.db "select model, cost_usd from usage_log order by id desc limit 3;"
# → google/gemma-4-26B-A4B-it|0.0
```

## 8. 實測結果（2026-11-08）

| 檢查 | 結果 |
|---|---|
| vLLM 純文字生成 | ✅ 2.1 s |
| tool calling | ✅ 1.2 s |
| streaming tool calling | ✅ 1.2 s |
| 引擎直接呼叫（約翰福音 3:16，3 輪） | ✅ 約 6 s |
| `verify-smoke.mjs` | ✅ 17/17 |
| `verify-chat.mjs`（`FHL_LOCAL_ENGINE=1`） | ✅ 全過，約 10 s |
| `usage_log.cost_usd` | ✅ 0.0 |

## 9. 踩過的坑

| 症狀 | 原因 | 解法 |
|---|---|---|
| `npm run build` → `Cannot find native binding` | Node 18 太舊，npm 跳過 `@tailwindcss/oxide` 的 ARM64 binary | 換 Node 24（§4），`rm -rf web/node_modules` 後重新 `npm ci` |
| 用量統計顯示 v8 有費用（每題約 $0.02） | 舊版 `_estimate_cost_usd()` 只認 `gemma-` 開頭；這台的 model id 是 `google/gemma-…` | 已修正（`server/chat.py`，改看 `/` 之後的名稱）。舊紀錄不會自動歸零 |
| `The model ... does not exist.`（404） | `.env` 的 `FHL_V8_MODEL_ID` 與 vLLM 的 model id 不符 | 照 `curl :8000/v1/models` 回傳的 `id` 填 |
| `Connection refused` | vLLM container 沒起來或還在載入 | `curl :8000/v1/models` 確認；container 由 root 管理 |
| 起第二個 vLLM 失敗 / OOM | 現有 vLLM 已佔約 110 GB unified memory | 不要另起，共用 `:8000` |

## 10. 回滾到 v6

`.env` 改 `FHL_ENGINE=v6.1`（需要 `ANTHROPIC_API_KEY`），重啟 uvicorn 即可。
