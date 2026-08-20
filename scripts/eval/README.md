# LLM 評估套件 — `scripts/eval/`

對任一版 RAG 引擎（v4–v7）跑一組聖經問題，評 **faithfulness／relevancy／
coverage**（1–5）並比較各引擎的分數、延遲與成本。用於引擎或 prompt 變更
前後的品質把關，屬「發佈前手動執行」，刻意不進 CI（會產生真實 API 費用）。

## 隱私：`questions.json` 不進版控

正式的 50 題題庫大多**取自 `logs/` 的真實使用者提問**，含個人化的信仰討論，
因此 `questions.json` 已在 `.gitignore`（與 `logs/` 同樣道理，見專案 CLAUDE.md）。
版控中只提供 `questions.sample.json`（一組通用、不涉個資的示例題，每類至少一題）。

自建題庫：
```bash
cp scripts/eval/questions.sample.json scripts/eval/questions.json
# 再依需要編輯／從自己的 logs 擴充；勿把真實使用者提問提交到公開 repo
```

## 執行（皆從 repo 根目錄）

```bash
# 1) 跑題 —— 產生 results_<engine>_<ts>.json（引擎 API 費用）
.venv/bin/python scripts/eval/run_eval.py --engine v6
.venv/bin/python scripts/eval/run_eval.py --engine v7           # 實驗引擎
#   --limit N / --ids id1 id2 ... 可跑子集；--out 指定輸出檔

# 2) 評分 —— 確定性檢查 + claude-opus-5 judge，產生 judged_<...>.json
.venv/bin/python scripts/eval/judge_eval.py scripts/eval/runs/results_v6_*.json

# 3) 比較 —— 多份 judged 檔並排成 markdown 報表
.venv/bin/python scripts/eval/report_eval.py scripts/eval/runs/judged_*.json
```

輸出都在 `scripts/eval/runs/`（gitignored — 含真實 API 回應）。

## 各檔角色

| 檔案 | 角色 |
|---|---|
| `questions.json` | 題庫（**gitignored**；自 `questions.sample.json` 複製後編輯）。每題：`id`、`category`、`source`、`expected`（該題的正確行為，adversarial 題即「應拒絕」）、`question`。 |
| `questions.sample.json` | 版控中的示例題庫（通用、非個資）。 |
| `run_eval.py` | 對指定引擎逐題呼叫 `bible_query`；以包裝共用的 `fhl_tools.TOOL_MAP` 擷取**完整**工具回傳（faithfulness 證據）；逐題記錄 token／成本／延遲；**每題落地存檔**（長跑可抗中斷）。 |
| `judge_eval.py` | 先做確定性檢查（經文連結 book/chap↔文字比對、「引文」須存在於工具證據、引用文章連結實際抓取＋摘錄），再由 `claude-opus-5` 評分。Judge 會被告知該引擎是否具備 web_search（不懲罰 v4–v6 沒有文章引用）。Judge 自身若因安全分類器 refuse（如答案點名資安工具），自動改用中性化題目＋`claude-opus-4-7` fallback。 |
| `report_eval.py` | 多引擎並排：總分、逐類分數、確定性錯誤數、延遲中位數、**各引擎成本**與 judge 成本。 |
| `eval_pricing.py` | 引擎與 judge 的計費（含 v7 web_search 每千次 $10）。 |

## 成本與已知限制

- **成本**：單題無對話歷史時較便宜。2026-08-20 全套 50 題實測：引擎每版約
  $1.5–2.3、judge 每版約 $2.1–2.7。有對話歷史的真實查詢會更貴。
- **確定性「引文檢查」有偽陽性**：引號樣式（「」vs『』）、跨節拼接、
  和合本 vs 雅威 用字差異都會被標為「未命中」，故 `unsupported quotes` 是
  **篩選訊號、非定論**——最終由 LLM judge 判定。
- **Judge 偏誤**：judge（Opus 5）比受測引擎（Sonnet 5）強且為不同模型，
  以降低 self-preference；但 LLM 評分本身仍有變異，重要結論宜看趨勢與逐題
  rationale，而非單一小數點差異。
- **單輪**：目前只評單輪問答；56 題多輪追問（如「那羅得的妻子呢？」）尚未納入。
