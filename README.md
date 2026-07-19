# 📖 信望愛 AI 聖經助手 — FHL Bible Bot

[信望愛（Faith, Hope, Love）](https://www.fhl.net/) 的 agentic 聖經研究助手。使用者以自然語言提問，Claude（Sonnet 5）自主呼叫 13 個針對 [信望愛聖經 API](https://bible.fhl.net/) 的專用工具 — 經文、希臘文/希伯來文原文分析、Strong's 字典、註釋、關鍵字搜尋 — 並整合成一篇附引用的回答；經文引用會自動連結回 bible.fhl.net（傳統版閱讀頁）或 tech.fhl.net/vui（新版界面）。

**AI 不會捏造資料**：每一項事實都必須來自工具回傳結果，每一個超連結都由 Python 以 regex 擷取＋書卷名對照表確定性地組出 — LLM 從不自行撰寫 URL。詳見下方 [確定性 vs 機率性](#確定性-vs-機率性deterministic-vs-probabilistic)。

- 正式網址：`https://tech.fhl.net/bible_bot/`（由 nginx 代理至 `127.0.0.1:7861`）
- 架構與逐檔說明：**[CODEBASE.md](CODEBASE.md)**
- 提交／協作規範：**[CLAUDE.md](CLAUDE.md)**

---

## 功能特色

- **串流聊天介面**（React SPA）— SSE 即時逐字串流、可摺疊的 🔧 工具呼叫記錄、停止按鈕、手機版面、繁體中文 UI
- **對話歷史** — 匿名 HttpOnly cookie 會話，各使用者的對話清單存於 SQLite
- **簡潔／詳盡 回答風格** — 每則訊息隨附風格參數，注入於 prompt cache 斷點之後，兩種風格共用同一份 cache
- **經文與 Strong's 超連結** — 確定性後處理；使用者可切換 傳統版／新版 連結目標，新版支援節層級錨點
- **用量統計** — 每筆查詢的 token／成本記錄（本月＋累計、個人＋全站），依 Sonnet API 定價估算
- **回饋機制** — 👍／👎／複製／留言，逐訊息記錄
- **斷線不掉答案** — 回答在 worker thread 中持久化；串流中關閉分頁也不會遺失回應

## 系統架構

```
瀏覽器（React SPA, web/）
   │  JSON + SSE  (/bible_bot/api/*)
   ▼
FastAPI（server/）── SQLite logs/chat.db（users/conversations/messages/feedback/usage_log）
   │  bible_query()
   ▼
RAG 引擎（scripts/claude_bible_rag_v4.py）
   │  Anthropic Messages API（tool_use 迴圈、prompt caching、串流）
   ▼                              ▲
Claude Sonnet 5 ──工具呼叫──▶  fhl_tools.py（13 個工具）
                                  │  HTTP GET
                                  ▼
                          bible.fhl.net/json/*.php
```

一個問題通常跑 1–4 輪工具呼叫（由模型決定、程式碼設上限），之後串流輸出最終回答。詳見 [CODEBASE.md → 請求生命週期](CODEBASE.md#請求生命週期一個問題的完整流程)。

## 快速開始（開發環境）

前置需求：Python 3.9+、Node 18+、Anthropic API key。

```bash
# 1. 後端相依套件
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 密鑰 — 絕不進版控
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 3. 啟動 API（同時在 /bible_bot/ 提供已建置的 SPA）
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 7861

# 4. 前端
cd web
npm ci
npm run dev     # 開發伺服器（含 proxy），或：
npm run build   # 輸出 web/dist，由 FastAPI 直接提供 — 不需重啟
```

打開 `http://127.0.0.1:7861/bible_bot/`。

## 正式環境部署

以 systemd **user** service 執行（不需 root）：

```ini
# ~/.config/systemd/user/fhl-bible-ui.service (ExecStart)
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 7861
```

```bash
systemctl --user restart fhl-bible-ui.service   # 後端變更後
cd web && npm run build                         # 前端變更後（不需重啟）
```

對外由 nginx 公開 — 見 `nginx-bible_bot-snippet.conf`（兩個 location 區塊；SSE 必須 `proxy_buffering off`）。

> ⚠️ 伺服器上**不可**使用 `uv run` — 見 CODEBASE.md → 部署與回滾。

## 設定速查表

| 項目 | 位置 | 預設值 |
|---|---|---|
| Anthropic API key | `.env` → `ANTHROPIC_API_KEY` | — |
| 模型 | `.env` → `FHL_V4_MODEL_ID` | `claude-sonnet-5` |
| 並行查詢上限 | 環境變數 `FHL_MAX_CONCURRENT` | 10 |
| Token 定價（成本估算） | `server/chat.py` → `PRICE_PER_MTOK_*` | Sonnet 5 intro→standard 依日期切換 |
| 經文連結新版 endpoint | `web/src/lib/verseLinks.ts` → `VUI_BIBLE_BASE` | `https://tech.fhl.net/vui/#/bible/` |
| 經文連結預設模式 | `web/src/lib/verseLinks.ts` → `DEFAULT_VERSE_LINK_MODE` | `"traditional"` |
| 回答風格指令 | `scripts/claude_bible_rag_v4.py` → `STYLE_INSTRUCTIONS` | 簡潔 |
| System prompt／工具規則 | `scripts/claude_bible_rag_v4.py` → `BIBLE_SYSTEM_PROMPT` | — |

## 確定性 vs 機率性（Deterministic vs Probabilistic）

分清哪些行為由**程式碼**控制（用測試驗證）、哪些由**模型**控制（用評估比較），是安全修改本系統的關鍵：

| 確定性 — 程式碼控制 | 機率性 — Sonnet 控制 |
|---|---|
| 全部 13 個 FHL 工具實作（純 HTTP＋解析） | 呼叫**哪些**工具、帶什麼參數、跑幾輪 |
| 經文／Strong's 超連結組建（regex＋書卷表 — LLM 從不寫 URL） | 回答文字：用詞、長度、結構、神學論述 |
| 瀏覽器端 傳統版／新版 連結改寫 | 引用是否寫成可連結化的格式（如 約翰福音 3:16） |
| 會話、DB schema、SSE 管線、並行上限 | 是否遵循 簡潔／詳盡 風格指令 |
| Token 計數與成本計算（取自 API `usage` 欄位） | 一則回答消耗多少 token |
| 輪數上限（`MAX_TOOL_ROUNDS`）、風格驗證、429 | 工具查無結果時的重試行為 |

完整對照與影響：[CODEBASE.md → 確定性 vs 機率性](CODEBASE.md#確定性-vs-機率性deterministic-vs-probabilistic)。

## 測試與 CI

- `e2e/verify-smoke.mjs` — 免費、不呼叫 LLM：health、session cookie、對話 CRUD、usage endpoint 格式、輸入驗證、SPA bundle。**每次 commit 前必跑。**
- `e2e/verify-chat.mjs` — 一次真實串流查詢（約 US$0.02–0.05）：SSE 契約、回答中的經文連結、用量記錄遞增。正式部署與任何 RAG 引擎變更前必跑。
- GitHub Actions `ci.yml` — 每次 push/PR 執行前端 typecheck＋build 與 Python compile 檢查（不需任何 secrets）。
- 部署：直接在伺服器上（VS Code Remote-SSH）執行 `./deploy.sh` — 拉最新程式碼、rebuild 前端、重啟服務、跑 smoke 測試。刻意**不**做 GitHub Actions 自動部署，避免把伺服器 SSH 私鑰放上 GitHub。

完整的上線前檢查表（哪種變更要跑哪些測試）見 [CODEBASE.md → 測試與發佈檢查表](CODEBASE.md#測試與發佈檢查表)。

## 目錄地圖

| 路徑 | 內容 |
|---|---|
| `server/` | FastAPI 後端：會話、聊天 SSE、SQLite 層 |
| `scripts/claude_bible_rag_v4.py` | 現行 RAG 引擎（v1–v3 保留為回滾備份） |
| `scripts/fhl_tools.py` | 13 個 FHL API 工具 |
| `scripts/app.py` | 舊版 Gradio 應用（舊正式環境，跑 v3、port 7860） |
| `web/` | React + Vite + Tailwind SPA |
| `e2e/` | 端對端（e2e）驗證腳本 |
| `nginx-*.conf` | 交給伺服器管理員的 nginx 片段 |
| `CODEBASE.md` | 逐檔架構說明 |
| `CLAUDE.md` | 提交規範與文件維護規則 |

## 授權／資料

聖經經文、字典與註釋均即時取自信望愛公開 API，版權屬各自版權方。對話資料只存在伺服器的 `logs/`，永不進入本 repository。
