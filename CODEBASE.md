# CODEBASE.md — FHL Bible Bot 架構指南

[README.md](README.md) 的姊妹文件。本文記錄每一個關鍵檔案、請求生命週期、
**哪些行為是確定性的（程式碼）、哪些是機率性的（LLM）**，以及正式環境變更的
測試／發佈流程。

目錄：
1. [頂層目錄結構](#頂層目錄結構)
2. [後端 — `server/`](#後端--server)
3. [RAG 引擎 — `scripts/`](#rag-引擎--scripts)
4. [前端 — `web/`](#前端--web)
5. [請求生命週期（一個問題的完整流程）](#請求生命週期一個問題的完整流程)
6. [確定性 vs 機率性（Deterministic vs Probabilistic）](#確定性-vs-機率性deterministic-vs-probabilistic)
7. [資料庫 schema](#資料庫-schema)
8. [成本記帳](#成本記帳)
9. [設定總覽](#設定總覽)
10. [測試與發佈檢查表](#測試與發佈檢查表)
11. [部署與回滾](#部署與回滾)

---

## 頂層目錄結構

| 路徑 | 角色 |
|---|---|
| `server/` | FastAPI 後端（新 UI）。會話、聊天 SSE、用量、SQLite。 |
| `scripts/claude_bible_rag_v6.py` | **現行正式**引擎（輸出/輸入調校：step-6 relevant data、選擇性引用經文、brief 具體格式、不做工具前敘述、不重複抓取搜尋結果經文、commentary 限最相關 2-4 節、優先 query_verse_citation 取代整章拉取）。 |
| `scripts/claude_bible_rag_v7.py` | **實驗性、未上線**（v6 + fhl.net `web_search`）。2026-08-20 評測顯示 web search 使當代議題的 faithfulness/coverage 下降（模型錯誤歸屬／捏造文章引文）且成本上升，故不用於正式環境，保留供未來開發。見 §RAG 引擎 與 `scripts/eval/`。 |
| `scripts/claude_bible_rag_v5.py` | 更早版本引擎，保留為回滾備份。**不可修改。** |
| `scripts/claude_bible_rag_v4.py` | 更早版本引擎，保留為回滾備份。**不可修改。** |
| `scripts/claude_bible_rag_v3.py` | 更前一版 — 舊版 Gradio 應用仍在使用。**不可修改。** |
| `scripts/claude_bible_rag.py`、`_v2.py` | 更早的引擎，保留為回滾備份。**不可修改。** |
| `scripts/fhl_tools.py` | 13 個 FHL API 工具（各版引擎共用）。 |
| `scripts/zh_hant.py` | 簡體→繁體字元表（2,475 筆）＋ `to_traditional()`。 |
| `scripts/gen_zh_hant_table.py` | 重建上述字元表（手動執行，需 OpenCC）。 |
| `scripts/test_zh_hant.py` | 字元表的回歸測試（`.venv/bin/python scripts/test_zh_hant.py`）。 |
| `scripts/app.py` | 舊版 Gradio 應用（舊正式環境、port 7860、import v3）。 |
| `web/` | React 18 + Vite + Tailwind SPA（TypeScript）。 |
| `e2e/` | 端對端驗證腳本（Node，無額外相依）。 |
| `logs/` | **執行期資料，已 gitignore**：`chat.db`（SQLite）＋舊版 JSON 備份。 |
| `.env` | **密鑰與部署設定，已 gitignore**：`ANTHROPIC_API_KEY`、可選 `FHL_ENGINE`（`v6`／`v7`／`v8`，未設＝`v6` 正式）、可選 `FHL_V4_MODEL_ID`、可選 `FHL_V7_WEB_SEARCH`（設 `0` 停用 web search）、v8 專用 `FHL_V8_BASE_URL`／`FHL_V8_MODEL_ID`。 |
| `nginx-bible_bot-snippet.conf` | 交給伺服器管理員貼進 nginx 的 location 區塊。 |
| `.github/workflows/` | `ci.yml`（建置檢查；不需 secrets）。部署一律在伺服器上執行 `./deploy.sh`。 |

引擎版本管理慣例：**永不修改舊版** — 複製為 `_vN+1.py`、改複本、再登錄到
`server/chat.py` 的 `ENGINE_MODULES`。

**跑哪一版引擎是設定、不是程式碼**：由 `.env` 的 `FHL_ENGINE` 決定（未設＝`v6`
正式），且**只 import 被選中的那一個模組**。因此 v8（需要本機 vLLM）留在
`scripts/` 對雲端機器完全無害 —— 雲端不設 `FHL_ENGINE` 就是 v6，本機 GPU 機
設 `FHL_ENGINE=v8`，兩台跟同一個 `main`。切換／回滾都只是改 `.env`＋重啟。
值若拼錯或無法辨識會退回 `v6`，不會讓服務起不來。

---

## 後端 — `server/`

### `main.py` — app factory
- 載入環境變數、強制 UTF-8 stdio、import 時執行 `db.init_db()`。
- API router 掛載兩次：`/api/*`（給 nginx 用，它會剝掉 `/bible_bot` 前綴）
  與 `/bible_bot/api/*`（單一行程服務與不經 nginx 的本機測試）。
- 以 `StaticFiles` 在 `/bible_bot/` 下提供 `web/dist` 建置好的 SPA
  — 它逐請求讀磁碟，所以**前端重新 build 後即時生效，不需重啟服務**。

### `sessions.py` — 匿名認證＋CRUD＋用量 endpoint
- `session_middleware`：每個 `/api` 請求都綁定到一個 user 列。Cookie
  `fhl_session`（32-byte urlsafe token、HttpOnly、SameSite=lax、180 天）。
  若不存在／不認得，會先嘗試採用舊版 Gradio cookie `fhl_session_id`
  （已遷移的使用者保留歷史），否則建新 user。結果：`request.state.user_id`
  永遠有值 — **沒有帳號、沒有密碼；cookie 就是身分。**
- Endpoints：`GET /api/health`、對話 CRUD（`GET/POST /conversations`、
  `GET/DELETE /conversations/{id}`）、`POST /messages/{id}/feedback`
  （action ∈ copy/good/bad/comment）、`GET /api/usage`
  （本月＋累計，個人＋全站）。
- 所有資料 endpoint 都以 `user_id` 過濾 — 跨使用者存取回 404。

### `chat.py` — 串流聊天 endpoint
- `POST /api/chat` body：`{conversation_id, message, style}`。
  驗證順序（全部確定性、全部在任何 LLM 費用發生**之前**）：
  空訊息 → 400；無效風格 → 400；非本人對話 → 404；
  超過 `FHL_MAX_CONCURRENT`（預設 10）個進行中查詢 → 429。
- 在 **worker thread** 執行 `bible_query()`；引擎的 `log_callback`／
  `stream_callback` 把事件推進 asyncio queue，endpoint 再轉成 SSE。
  事件：`tool_log`（每次工具呼叫一行）、`text_delta`（原始串流 token）、
  `done`（`{message_id, title, content}` — `content` 是**後處理過**含連結的
  最終回答，前端用它替換原始串流文字）、`error`。
- **持久化在 worker、不在 generator**：瀏覽器斷線後 thread 仍會跑完並存檔。
  停止按鈕只停止「觀看」。
- 成本記帳：把 `usage` dict 傳入 `bible_query(usage_out=...)`，成功**與**
  失敗都經由 `_log_usage()` 記錄（失敗前燒掉的 token 一樣有計費）。
  定價常數與 intro→standard 日期切換就在本檔開頭。`_log_usage` 外層包
  broad try/except — 記帳絕不能弄壞聊天。

### `db.py` — SQLite 層
- `logs/chat.db`、WAL 模式、每次操作一條短命連線
  （對 FastAPI threadpool worker 安全）。
- Schema 以 `CREATE TABLE IF NOT EXISTS` 在啟動時套用 — 新增**資料表**
  不需 migration script；對既有資料表加**欄位**才需要。
  見 [資料庫 schema](#資料庫-schema)。
- `migrate_json.py` — 一次性、可重跑的舊版 Gradio `logs/user_*.json` 匯入
  （正式環境已執行；JSON 保留為備份）。

---

## RAG 引擎 — `scripts/`

### `claude_bible_rag_v6.py` — 現行正式引擎

關鍵常數（檔案開頭）：`MODEL_ID`（預設 `claude-sonnet-5`，可用環境變數
`FHL_V4_MODEL_ID` 覆寫 — 刻意與 v3 的 `FHL_MODEL_ID` 分開）、
`MAX_TOOL_ROUNDS = 10`、`STYLE_INSTRUCTIONS`（簡潔／詳盡 system 區塊）、
`FHL_READ_URL`／`LINK_VERSION`（經文連結目標）。

**`bible_query(user_question, tools, history, log_callback, stream_callback,
style, usage_out) -> str`** — agentic 迴圈：

1. 組請求：system prompt（`BIBLE_SYSTEM_PROMPT`）帶 prompt cache 斷點，
   風格區塊放在斷點**之後**（簡潔與詳盡共用同一份 cache），工具 schema
   由 Python 函式的簽名／docstring 自動產生。
2. 輪迴圈（≤ `MAX_TOOL_ROUNDS`）：串流模型回應；若
   `stop_reason == "tool_use"`，**在 Python 端**執行被要求的工具
   （未知工具名或壞參數會變成 error tool-result，不會 crash），
   附上 rolling cache 斷點後進下一輪。
3. 得到最終回答後：以 `_postprocess_answer()` 後處理並回傳
   （簡體→繁體 → 經文連結 → Strong's 連結）。
4. `usage_out`（可選 dict）：**每一輪** API 之後就地更新累計的
   `uncached_in / out / cache_read / cache_write / model` —
   即使後面某輪拋例外，累計值也保得住。這是用量記帳的資料來源。

**超連結後處理 — 防幻覺（anti-hallucination）設計。** 模型被指示用純文字
寫引用（約翰福音 3:16）、用標準格式寫 Strong's 編號（`SNG00025`／
`SNH02617`），且**絕不自己寫 URL**。之後：
- `linkify_bible_references()` — 對最終文字跑 regex；書卷名經由 FHL 書卷表
  （`fhl_tools`）解析；URL 由 `_build_read_url()` 組出（章層級、不帶 `sec`
  參數 — 刻意開整章）。
- `linkify_strongs_numbers()` — 比對 `SN[GH]\d{1,5}`、補零正規化、連到
  `bible.fhl.net/new/s.php?N={0|1}&k={num}`；已在 markdown 連結內的編號會跳過。

因此連結永遠不可能指到 regex＋書卷表沒組出的地方。殘餘的（機率性）風險是
**漏連結** — 模型若寫出 regex 不認得的引用格式，該段文字就單純不加連結。

### `claude_bible_rag_v7.py` — 實驗性引擎（v6 + fhl.net web search，未上線）

v7 = v6 再加 Anthropic 伺服器端 `web_search`（限定 `allowed_domains=["fhl.net"]`），
讓「信仰 vs. 當代議題」（演化論、尼安德塔人、同志議題…）能搜信望愛站文章。
**目前不用於正式環境**，`server/chat.py` import 的是 v6；v7 保留供未來開發。

**為何暫不上線（2026-08-20 評測結論，見 `scripts/eval/`）**：50 題 × 三版
評測顯示 web search 反而**降低**當代議題品質 —
- faithfulness 3.6（v7）vs 4.4（v6）：模型會把句子加引號並歸給某篇信望愛
  文章，但抓取該頁面後找不到該段文字（錯誤歸屬／捏造，評測列
  cont01/cont02/doct01）。
- coverage 3.9（v7）vs 4.8（v6）。
- 成本：每題約 $0.045 vs v6 約 $0.031，另加每千次搜尋 $10。

升級 v7 前需先修 prompt：**只有搜尋結果中逐字出現的文章文字才可加引號引用**，
再重跑 `scripts/eval` 確認當代類別回升。

技術要點（保留供未來）：
- `WEB_SEARCH_TOOL` 用**基本版 `web_search_20250305`、不用 `20260209`**：
  新版 dynamic filtering 會在伺服器端 container 跑 code execution，後續
  請求必須帶回 `container_id`，漏帶下一輪就 400（2026-08-20 09:38 production
  事故：查詢在第 3 輪炸掉、回答遺失）。迴圈仍防禦性地把 `response.container.id`
  帶回，以防日後換回 container 型工具。
- 迴圈配套：`stop_reason == "pause_turn"` → 原樣附回 assistant 訊息續跑，
  已串流文字累積在 `carried_text` 併入最終回答；
  `usage.server_tool_use.web_search_requests` 記進 `usage_out["web_search"]`，
  `server/chat.py` 以每次 $0.01（$10/1,000）計入成本（v6 下此值為 0，計費碼靜置）。
- DuckDuckGo 免費方案曾被評估但實測（2026-08-20）同 IP 連續 1-2 次請求即被
  rate-limit，多人共用不可靠，故選原生 server tool。
- 引擎例外現在會印 traceback 到 stderr（→ `logs/uvicorn_ui.log`）——此為
  v7 開發時加入 `server/chat.py` 的改善，v6 上線同樣受惠。

### `zh_hant.py` — 簡體字清理（v5 新增）

system prompt 已經要求「Output language: 繁體中文 (zh-tw)」，但清查
`logs/chat.db`（2026-04-30 ～ 2026-08-13）發現 **288 篇回答中有 8 篇**
（約 2.8%）在整體正確的繁體句子裡夾雜簡體字 —「核心问题」「强调」
「①银子作为在众人眼前证明」— 集中在較長的原文分析回答（其中一篇甚至
夾了俄文「инфинитив绝对式」）。純靠 prompt 措辭壓不住，因此改用確定性後處理。

**為什麼不直接用 OpenCC。** 拿同樣 288 篇回答實測：

| 方式 | 被改動的回答 | 問題 |
|---|---|---|
| OpenCC `s2t` | 114 / 288 | 吃→喫（116 次）、群→羣（63）、才→纔（29）、里→裏、台→臺 |
| OpenCC `s2twp` | 168 / 288 | 再加上詞彙置換（對象→物件、信息→資訊）與整字刪除 |
| `zh_hant`（本模組） | **8 / 288** | 只改真正的簡體字 |

對一個逐字引用和合本的工具來說，為了修 8 篇而破壞 114 篇不划算。

**做法：**純字元表 `str.translate`，收錄條件為
（1）Big5 編不出來、（2）OpenCC `t2s` 不會改動它（排除 Big5 以外的繁體
異體字 — 裏／麽／衆，和合本兩種寫法都用，改了等於竄改經文）、
（3）OpenCC `s2tw` 恰好對應到另一個字。用 `s2tw` 而非 `s2t`，才會得到
台灣用字（为→**為**、众→**眾**、启→**啟**）。`祢` 在產生器的 KEEP 名單裡
（「願祢的旨意成就」的敬語，不是簡體字）。

**成本：**目前最長的一篇回答（10,149 字）0.9 ms，且發生在串流結束之後的
worker thread — 不影響首字延遲與串流速度。

**已知限制：**表中有 121 個字理論上一對多（发→發／髮、别→別／彆），
字元表一律取常用形；四個月的實際流量沒出現過。若真的出現，正解是對該段
做詞彙感知轉換，而不是把表放寬。

表由 `gen_zh_hant_table.py` 產生並直接 commit（伺服器執行期不需要 OpenCC
相依）；`test_zh_hant.py` 會拿整個 `chat.db` 做回歸，確認「只改那 8 篇」。

Sonnet 5 注意事項：`temperature/top_p/top_k` 參數收下但忽略（模型會拒絕
非預設值）；adaptive thinking 預設啟用（未設 `thinking` 參數）；
`max_tokens=16384`。

### `fhl_tools.py` — 13 個確定性工具

所有工具都是對 `bible.fhl.net/json/*.php` 的單純 `requests` GET＋回應裁切。
書卷表（`_load_book_table`）在 **import 時**從 FHL 的 `listall.html` 抓一次
— 離線環境 import 會失敗（CI 因此只做 compile 檢查、不 import）。

| 工具 | 用途 |
|---|---|
| `get_bible_verse`／`get_bible_chapter` | 單節／整章經文，任意版本 |
| `query_verse_citation` | 解析 約3:16 這類引用 |
| `search_bible_advanced` | 關鍵字搜尋，可限書卷範圍 |
| `get_word_analysis` | 單節希臘文／希伯來文逐字剖析 |
| `lookup_strongs`／`search_strongs_occurrences` | Strong's 字典／全部出現處 |
| `get_commentary`／`search_commentary`／`list_commentaries` | 註釋 |
| `get_topic_study` | 主題研經索引 |
| `list_bible_versions`／`get_book_list` | 版本／書卷 metadata |

`ALL_TOOLS`／`TOOL_MAP` 輸出工具集；引擎從 docstring 產生 Anthropic 工具
schema，所以 **docstring 的措辭就是 prompt engineering** — 它會改變模型行為
（機率性表面），函式本體則是確定性的。

### 舊版引擎
`claude_bible_rag_v3.py` 供仍在運行的 Gradio 應用（`app.py`、port 7860、
經 `FHL_MODEL_ID` 使用 Opus 4.7）。v1/v2/v4/v5 是回滾備份、v7 是實驗引擎、
v8 是本機 Gemma 評估引擎。`server/chat.py` 在啟動時**只 import `FHL_ENGINE`
指定的那一個**（未設＝v6 正式），其餘檔案完全不會被載入。

---

## 前端 — `web/`

技術堆疊：React 18、TypeScript、Vite 6、Tailwind 4、`react-markdown`＋GFM、
lucide-react 圖示。建置為靜態檔（`npm run build` = `tsc -b && vite build`）；
正式環境沒有 Node 行程。Base path `/bible_bot/`（vite `base`）。

| 檔案 | 角色 |
|---|---|
| `src/App.tsx` | 版面、header（FHL logo）、對話狀態、自動捲動、錯誤 toast。持有兩個持久化設定：回答風格（`fhl_answer_style`）與經文連結模式。 |
| `src/api/client.ts` | CRUD＋`getUsage()` 的型別化 fetch 包裝。`API_BASE` 取自 vite 的 `BASE_URL`。 |
| `src/api/chatStream.ts` | 以 fetch POST 手寫的 SSE parser（處理 `tool_log/text_delta/done/error`，429 顯示友善訊息）。 |
| `src/api/types.ts` | 全部共用型別（`Message`、`UsageResponse`…）。 |
| `src/hooks/useConversation.ts` | 掌管當前聊天：載入歷史、樂觀 UI、delta 串流、中止／重新掛接。 |
| `src/lib/liveStreams.ts` | 以對話 id 為 key、放在 React **之外**的進行中串流 — 回答中切換對話不會中止；切回來即時重新掛接。 |
| `src/lib/verseLinks.ts` | **經文連結設定模組。** `DEFAULT_VERSE_LINK_MODE` 與 `VUI_BIBLE_BASE` 兩個可調常數、localStorage 持久化，以及 `transformVerseHref()` — 渲染時把儲存的 `read.php` href 改寫為 `tech.fhl.net/vui/#/bible/書卷章[:節]`。節錨點是從引用**文字**還原的（儲存的 href 只有章）。非 read.php 連結原樣通過。 |
| `src/components/Sidebar.tsx` | 對話清單、經文連結 傳統版／新版 切換、用量統計 按鈕＋modal（本月＋累計費用）。 |
| `src/components/ChatMessage.tsx` | 訊息泡泡＋markdown 渲染。`a` renderer 套用 `transformVerseHref` 並強制 `target="_blank"`。 |
| `src/components/ChatInput.tsx` | 自動伸縮 textarea、IME 組字保護（打中文不會中途送出）、簡潔／詳盡 切換、停止按鈕。 |
| `src/components/ToolCallLog.tsx` | 可摺疊 🔧 工具呼叫記錄 — 工具執行中展開、回答開始後自動收合。 |
| `src/components/MessageActions.tsx` | 複製／👍／👎／留言 → feedback endpoint。 |

值得記住的設計決策：經文連結改寫是**瀏覽器端渲染時**進行（不改儲存內容），
所以 傳統版／新版 設定對舊對話同樣生效，endpoint 變更也永遠不需要資料遷移。

---

## 請求生命週期（一個問題的完整流程）

```
1. UI  POST /api/chat {conversation_id, message, style}        [確定性]
2. server/chat.py 驗證、檢查並行上限                            [確定性]
3. worker thread：bible_query()
   第 1..N 輪：
     Claude 決定：直接回答，或呼叫工具（哪些？參數？）          [機率性]
     fhl_tools.* 執行 HTTP 呼叫、回傳 JSON                      [確定性]
     （僅 v7 實驗引擎）web_search 在 Anthropic 端執行，僅搜 fhl.net [搜尋詞：機率性]
     每次呼叫發一個 tool_log SSE 事件 → UI 🔧 記錄              [確定性]
   最後一輪串流 text_delta 事件                                 [文字內容：機率性]
4. _postprocess_answer() 簡體→繁體、加經文＋Strong's 連結       [確定性]
5. db.append_turn() 存檔；_log_usage() 依 API usage 欄位
   記錄 token 與成本                                            [確定性]
6. SSE `done` 帶回含連結的最終回答；UI 替換顯示                 [確定性]
7. 渲染：markdown → HTML；依 傳統版/新版 設定改寫經文 href      [確定性]
```

---

## 確定性 vs 機率性（Deterministic vs Probabilistic）

**為什麼重要：**確定性的部分用*測試*驗證（過或不過）；機率性的部分用*評估*
比較（行為隨模型、prompt 甚至同樣輸入的不同執行而漂移）。當一個正式環境
變更碰到右欄時，預期的是分佈的移動、不是 pass/fail — 要前後抽樣比較回答，
不能只跑 e2e。

### 確定性 — 程式碼控制

| 行為 | 位置 |
|---|---|
| 13 個工具實作（HTTP、解析、裁切） | `scripts/fhl_tools.py` |
| 工具分派、未知工具／壞參數錯誤處理、輪數上限（10） | `claude_bible_rag_v6.py` 迴圈（v7 另有 `pause_turn` 續跑） |
| web_search 網域限制（`allowed_domains=["fhl.net"]`）與次數上限（3） | `WEB_SEARCH_TOOL` 定義（僅 v7 實驗引擎；Anthropic 端強制執行） |
| 經文與 Strong's 連結組建（regex＋書卷表；LLM 從不寫 URL） | v6 的 `linkify_*` |
| 簡體字轉繁體（字元表，非 OpenCC） | `scripts/zh_hant.py` |
| 傳統版/新版 href 改寫＋節錨點 | `web/src/lib/verseLinks.ts` |
| 會話身分、cookie 處理、使用者隔離 | `server/sessions.py` |
| 輸入驗證（空訊息/風格/擁有權/429）— 在任何 LLM 費用之前 | `server/chat.py` |
| SSE 事件契約與 worker thread 持久化 | `server/chat.py` |
| DB schema、CRUD、feedback 記錄、用量彙總 | `server/db.py` |
| Token 計數（讀 API `usage`）與成本計算（含 intro→standard 切換） | `server/chat.py` |
| Prompt cache 斷點位置 | v4 請求組裝 |
| 所有 UI 行為（串流顯示、切換、modal、markdown） | `web/src` |

### 機率性 — Sonnet 控制

| 行為 | 受什麼影響（你的調整桿） |
|---|---|
| 呼叫哪些工具、什麼參數、幾輪 | `BIBLE_SYSTEM_PROMPT` 規則＋`fhl_tools.py` 的**工具 docstring** |
| 回答文字：用詞、結構、長度、神學論述 | system prompt、`STYLE_INSTRUCTIONS`、模型選擇 |
| 引用是否寫成可連結化格式（約翰福音 3:16）、Strong's 是否寫成標準 `SNG#####` | system prompt 的格式規則（linkifier 之後要嘛生效、要嘛靜默跳過） |
| 搜尋 0 筆結果時的重試行為 | prompt 中「NEVER give up」段落 |
| 是否動用 web_search（該省則省）、搜尋關鍵字、是否附文章連結 | prompt 中「Web search」段落＋Answer Style 的 Web article citations 規則 |
| 簡潔 vs 詳盡 的遵循程度 | 風格區塊措辭 |
| 每則回答的 token 消耗（成本） | 模型＋prompt＋問題 |
| 每輪延遲 | 模型＋Anthropic 負載（adaptive thinking 預設啟用） |

**灰色地帶：**工具 *schema* 由 docstring 產生 — schema 產生本身是確定性的，
但模型如何理解那些描述不是。改 docstring 等於改 prompt，要照 prompt 變更
處理（前後抽樣比較）。

---

## 資料庫 schema

`logs/chat.db`（SQLite、WAL）。所有時間戳為 `YYYY-MM-DD HH:MM:SS` 本地時間
（字串比較即時間先後）。

| 資料表 | 欄位 | 備註 |
|---|---|---|
| `users` | id（cookie token）、created_at | 無 PII、無密碼。 |
| `conversations` | id（uuid）、user_id、title、created_at、updated_at | 標題＝第一個問題前 30 字。 |
| `messages` | id、conversation_id、role、content、tool_log、created_at | `content` 是含連結的最終 markdown。 |
| `feedback` | id、message_id、user_id、action、comment、created_at | Append-only 事件記錄（保留 👍→👎 的變化）。 |
| `usage_log` | id、user_id、conversation_id、model、input_tokens、output_tokens、cache_read_tokens、cache_write_tokens、cost_usd、created_at | **每筆查詢一列。**刻意與 `messages` 分開，刪除對話不會抹掉花費紀錄。 |

`db.get_monthly_usage(user_id=None)` 已提供逐月彙總（新到舊），
供之後畫用量圖表使用。

---

## 成本記帳

- 引擎經由 `usage_out` 回報每筆查詢的累計 token（每一輪 API 後更新，
  出錯也保得住部分用量）。
- `server/chat.py::_estimate_cost_usd()` 把 token 換算成 USD：
  `SONNET5_INTRO_UNTIL = 2026-08-31` 之前用 `PRICE_PER_MTOK_INTRO`
  （$2/$10，cache write 2.50、cache read 0.20），之後用
  `PRICE_PER_MTOK_STANDARD`（$3/$15/3.75/0.30）。**在查詢當下計算**，
  所以已存的列保留歷史上正確的費率。web_search 次數
  （`usage["web_search"]`，v7 起）另以 `WEB_SEARCH_PRICE_PER_QUERY`
  （$10/1,000 次）計入。
- **換模型時**（`FHL_V4_MODEL_ID`）記得更新這些常數 —
  每列的 `model` 欄位讓舊資料仍可歸因。
- 顯示於側欄 用量統計 modal（`GET /api/usage`）：本月＋累計、
  個人＋全站。統計自 2026-07 開始 — 更早的對話沒有記錄。

---

## 設定總覽

| 調整桿 | 位置 | 效果 |
|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` | Anthropic 認證（僅伺服器端）。 |
| `FHL_V4_MODEL_ID` | `.env` | 新 UI 的模型（預設 `claude-sonnet-5`）。v3/Gradio 用的是另一個 `FHL_MODEL_ID`。 |
| `FHL_MAX_CONCURRENT` | service 環境變數 | 並行查詢上限（預設 10，超過回 429）。 |
| `PRICE_PER_MTOK_INTRO/STANDARD`、`SONNET5_INTRO_UNTIL` | `server/chat.py` | 成本估算。 |
| `FHL_V7_WEB_SEARCH` | `.env` | 設 `0` 停用 fhl.net web search（僅對 v7 實驗引擎有效）。 |
| `MAX_TOOL_ROUNDS` | `claude_bible_rag_v6.py` | Agentic 輪數硬上限。 |
| `WEB_SEARCH_TOOL`（`max_uses`、`allowed_domains`） | `claude_bible_rag_v7.py`（實驗，未上線） | 每次查詢的搜尋次數上限與網域白名單。 |
| `WEB_SEARCH_PRICE_PER_QUERY` | `server/chat.py` | web search 計費（$10/1,000 次；v6 下靜置）。 |
| `BIBLE_SYSTEM_PROMPT`、`STYLE_INSTRUCTIONS` | `claude_bible_rag_v6.py` | 最主要的機率性調整桿。 |
| `FHL_READ_URL`、`LINK_VERSION` | `claude_bible_rag_v6.py` | 傳統版連結目標（會存進回答）。 |
| `DEFAULT_VERSE_LINK_MODE`、`VUI_BIBLE_BASE` | `web/src/lib/verseLinks.ts` | 新版連結 endpoint＋預設模式（僅渲染時）。 |
| Cookie 名稱／效期 | `server/sessions.py` | 會話身分。 |

---

## 測試與發佈檢查表

### 測試清單

| 檢查 | 指令 | 成本 | 涵蓋 |
|---|---|---|---|
| TypeScript＋build | `cd web && npm run build` | 免費 | 型別錯誤、bundle 建置 |
| Python compile | `.venv/bin/python -m compileall -q server scripts` | 免費 | 後端＋各版引擎語法 |
| **Smoke e2e** | `node e2e/verify-smoke.mjs` | 免費 | health、cookie 會話、對話 CRUD＋隔離、`/api/usage` 格式、聊天輸入驗證（400/404 路徑）、SPA 服務現行 bundle |
| **Chat e2e** | `node e2e/verify-chat.mjs` | 約 US$0.02–0.05（1 次真實查詢） | 完整 SSE 契約、tool_log 事件、回答中的經文連結、`usage_log` 遞增且 cost > 0 |
| 瀏覽器人工檢查 | 硬重整 `http://127.0.0.1:7861/bible_bot/` | 免費 | 串流顯示、各切換、modal、手機版面 |

兩個 e2e 腳本預設打 `http://127.0.0.1:7861/bible_bot`，可用
`BASE_URL=... node e2e/...` 指向其他實例。輸出 `PASS/FAIL — 名稱` 行、
失敗時以非零碼結束（與 fhl-bible-vui repo 同一慣例）。

### 哪種變更要跑什麼

| 變更範圍… | 部署前必跑 |
|---|---|
| 只動 `web/src` | build＋smoke e2e＋瀏覽器硬重整檢查 |
| `server/*` | compileall＋smoke e2e＋**重啟服務**＋chat e2e |
| `claude_bible_rag_v6.py`（或實驗 v7）的 prompt/工具/docstring | 以上全部**加上**抽樣回答比較（機率性變更 — 用 3–5 個代表性問題前後對比工具鏈與回答品質；或跑 `scripts/eval` 全套） |
| `zh_hant.py` 字元表 | `.venv/bin/python scripts/test_zh_hant.py`（會拿 `logs/chat.db` 全部訊息做回歸） |
| 換模型（`FHL_V4_MODEL_ID`） | 同 prompt 變更＋更新定價常數 |
| 定價常數 | smoke e2e＋一次 chat e2e，然後核對 用量統計 數字 |
| DB schema | 先寫好遷移路徑（新資料表自動建立；既有資料表加**欄位**需 `ALTER TABLE`）、備份 `logs/chat.db`、再跑 smoke e2e |

### LLM 評估套件 — `scripts/eval/`

50 題評測集，七類：exegesis 15、word_study 6、doctrine 6、figure_history 6、
synthesis 3、contemporary 8、adversarial 6，可對 **任一版引擎（v4–v7）**
執行並互相比較。**`questions.json` 因大多取自真實使用者提問而 gitignored**
（見 `scripts/eval/README.md` 的隱私說明）；版控只提供 `questions.sample.json`
（通用示例，`cp` 後自行擴充）。三支指令（皆從 repo 根目錄執行）：

```bash
.venv/bin/python scripts/eval/run_eval.py --engine v7        # 跑題（引擎費用）
.venv/bin/python scripts/eval/judge_eval.py scripts/eval/runs/results_v7_*.json
.venv/bin/python scripts/eval/report_eval.py scripts/eval/runs/judged_*.json
```

- `run_eval.py` — 逐題呼叫該版 `bible_query`；以包裝共用的
  `fhl_tools.TOOL_MAP` 擷取**完整**工具回傳（faithfulness 證據）；
  逐題記錄 token 用量與成本（`eval_pricing.py`，含 v7 web_search 計費）。
  `--limit N`／`--ids id...` 可跑子集。
- `judge_eval.py` — 先做**確定性檢查**（經文連結 book/chap 與連結文字比對、
  「引文」須存在於工具證據、引用文章連結實際抓取＋摘錄），再由
  **claude-opus-5** 評 faithfulness／relevancy／coverage（1-5）＋violations。
  Judge 會被告知該引擎是否具備 web_search，避免懲罰 v4–v6 沒有文章引用。
  adversarial 題的正確行為是**拒絕**（coverage 高分）。
  **Judge 自身 refusal 處理**：當答案本身提及資安工具（如 SSH 弱密碼腳本
  題，答案雖正確拒絕但點名 Hydra/Medusa），Opus 5 judge 的安全分類器會
  `stop_reason="refusal"` 回空內容；此時自動改用中性化題目描述＋
  fallback judge（`claude-opus-4-7`，不同分類器）重評。仍失敗記 -1
  （report 的平均排除 ≤0 分，不當作 0 拖低分數）。
- `report_eval.py` — 多份 judged 檔並排：總分、逐類分數、確定性錯誤數、
  延遲中位數、**各引擎成本**與 judge 成本。
- 輸出在 `scripts/eval/runs/`（gitignored）。**2026-08-20 首次全套實測**
  （v7/v6/v4）：引擎每版 $1.5–2.3、judge 每版 $2.1–2.7（單輪、無歷史，
  遠低於原估）。屬「發佈前手動執行」，刻意不進 CI。
- **首輪關鍵結論**：三版整體分數相近（F/R/C 均約 4.3／4.9／4.5），但
  **v7 的 web search 反而拉低當代議題品質** — contemporary 類 faithfulness
  v7 3.6 vs v6 4.4、coverage v7 3.9 vs v6 4.8：judge 抓到 v7 把句子加引號
  歸給某篇信望愛文章、但抓取頁面找不到該段（錯誤歸屬／捏造）。故正式環境
  維持 v6，v7 留待修正 prompt（只引用搜尋結果中逐字出現的文章文字）後再評。

### CI（GitHub Actions）與部署方式

- `ci.yml` — 每次 push/PR：前端 `npm ci && npm run build`（含 `tsc`）、
  後端 `python -m compileall server scripts`。CI **刻意不 import、不呼叫
  LLM**：import 引擎會連網抓 FHL 書卷表，chat 測試要花錢 —
  這些改在伺服器上用 e2e 腳本跑。`ci.yml` 只在 GitHub 的 runner 上
  建置程式碼，**不需要任何 repo secrets**。
- **部署不走 GitHub Actions** — 這是刻意的安全決策：自動部署需要把能
  登入 tech.fhl.net 的 SSH 私鑰存成 GitHub secrets，等於讓 GitHub 帳號
  成為進入伺服器的途徑（帳號被盜或惡意 workflow 變更即可觸及主機）。
  開發本來就透過 VS Code Remote-SSH 在伺服器上進行，部署只是
  rebuild＋restart，在伺服器上執行 `./deploy.sh` 即可，不需額外憑證。

### 提交規範

見 [CLAUDE.md](CLAUDE.md)：前綴 `UI:`／`bug:`／`other:`、標題中文為主、
commit 前先跑 e2e。

---

## 部署與回滾

伺服器上兩套獨立堆疊並行：

| | 新 UI（本產品） | 舊版（不動） |
|---|---|---|
| Service | `fhl-bible-ui.service`（systemd --user） | `fhl-bible-bot.service` |
| Port | 7861 | 7860 |
| 引擎／模型 | v6／Sonnet 5（`FHL_V4_MODEL_ID`；v7 實驗未上線） | v3／Opus 4.7（`FHL_MODEL_ID`） |
| 公開路徑 | `tech.fhl.net/bible_bot/` | `tech.fhl.net/bible_tool_bot/` |

日常操作：

```bash
systemctl --user restart fhl-bible-ui.service   # 後端變更
systemctl --user status fhl-bible-ui.service    # 健康檢查（本帳號讀不到 journalctl）
curl -s 127.0.0.1:7861/bible_bot/api/health     # → {"status":"ok"}
cd web && npm run build                         # 前端變更 — 立即生效，不需重啟
```

注意事項：
- 伺服器上**絕不使用 `uv run`**：repo 根目錄的 `pyproject.toml` 屬於另一個
  需要 Python 3.11 的無關專案；venv 是 3.9。一律
  `.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 7861`。
- 高埠對外網防火牆封鎖；nginx（80/443）是唯一公開路徑。nginx 變更需要
  伺服器管理員（`nginx-bible_bot-snippet.conf`）。
- **引擎回滾：**把 `server/chat.py` 的 import 換成舊版
  `claude_bible_rag_v*` 後重啟。**模型回滾：**改 `.env` 的
  `FHL_V4_MODEL_ID` 後重啟（記得定價常數）。
- 任何 schema 變更前先備份：`sqlite3 logs/chat.db ".backup backup.db"`。
