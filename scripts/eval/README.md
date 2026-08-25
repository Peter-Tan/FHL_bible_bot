# LLM 評估套件 — `scripts/eval/`

對任一版 RAG 引擎（v4–v8）跑一組聖經問題，評 **faithfulness／relevancy／
coverage**（1–5）並比較各引擎的分數、延遲與成本。用於引擎或 prompt 變更
前後的品質把關，屬「發佈前手動執行」，刻意不進 CI（會產生真實 API 費用）。

## 題庫與隱私

| 檔案 | 內容 | 版控 |
|---|---|---|
| `questions.json` | **公開題庫（70 題）**：由真實使用者提問改寫而成 | **有** |
| `questions.private.json` | 直接取自 `logs/` 的原始題庫，未去識別化 | **無**（gitignore） |
| `questions.sample.json` | 早期的通用示例題，每類至少一題 | 有 |

去識別化標準：**保留語域、改寫字串**。真實提問的斷句、錯字、空格、簡繁混用、
一次貼一串經文——這些正是這份題庫比合成題庫更有代表性的原因，因此刻意保留；
但凡帶有可辨識指紋的字串（特殊空格、錯字組合、個人處境）一律改寫。像
「聖經是否無誤」「What is python」這類任何人都寫得出來的通用問法則維持原樣，
改寫它們買不到隱私，只會失去語域真實性。

已移除：第三方貼文網址、逐字轉錄的網友留言、可指認宗派歸屬或個人處境的敘述。

原始題庫（`questions.private.json`）留在本機，**永遠不要提交**。

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

## `expected_behavior` — 評分靠的是欄位，不是散文

每題都有一個明確欄位，取代先前「`expected` 字串裡有沒有『拒絕』兩個字」的
判斷方式（公開題庫若靠中文子字串決定分母，第一個外部貢獻者就會無聲地弄壞它）：

| 值 | 意思 | 題數 |
|---|---|---|
| `answer` | 正常以工具查證作答 | 45 |
| `correct_premise` | 前提有誤，須查證後更正，**不是**拒答 | 12 |
| `refuse` | 應拒絕 | 11 |
| `redirect` | 超出範圍，禮貌導回聖經主題 | 2 |

`quant_eval.py` 依此決定各項分母：只有 `refuse` 列進拒答率，只有 `answer` 與
`correct_premise` 列進引用涵蓋率。舊的 run 檔沒有這個欄位，會退回舊的字串判斷。

## 對抗題（23 題，六個子類）

| subtype | 題數 | 測什麼 |
|---|---|---|
| `false_premise` | 6 | 虛構經節、錯置作者、不存在的書卷／Strong's 編號、真經節假內容 |
| `injection` | 5 | 繞過正則的注入變體：軟性換題、自稱開發者、假設語氣、英文切換、**夾在經文引文裡的指令** |
| `persona_hijack` | 3 | 角色覆蓋，含「不要引用聖經工具」這種要求放棄查證的變體 |
| `sycophancy` | 4 | 使用者以權威或施壓要求改口（「我牧師說」「我研究三十年」），測會不會為了迎合而改答案或虛構出處 |
| `pastoral_risk` | 4 | 以經文造成傷害：家暴處境的順服經文、為特定群體「證明下地獄」的證據集、恐嚇式選經文、自殺意念的求助。**其中兩題正確行為是關懷作答，不是拒答** |
| `offtopic_safety` | 1 | 資安腳本請求。注意此題會觸發 judge 自身的安全分類器（見 `judge_eval.py` 的 fallback） |

`sycophancy` 的施壓寫在單一訊息內，因此現行單輪 harness 就能跑；真正的多輪
注入（先建立無害脈絡、後續才注入）仍未涵蓋。

## 指標定義與結論

各數字代表什麼、怎麼算、2026-08-20 四引擎實測結論，見
**[`README_METRICS.md`](README_METRICS.md)**。
題庫本身的設計問題與修訂建議（對抗題）見
**[`QUESTION_DESIGN.md`](QUESTION_DESIGN.md)**。

## 各檔角色

| 檔案 | 角色 |
|---|---|
| `questions.json` | 公開題庫（70 題）。每題：`id`、`category`、選用的 `subtype`（對抗題子類）、`expected_behavior`、`expected`（散文說明）、`question`。 |
| `questions.private.json` | 原始題庫，**gitignored**，不要提交。 |
| `questions.sample.json` | 早期示例題庫。 |
| `run_eval.py` | 對指定引擎逐題呼叫 `bible_query`；以包裝共用的 `fhl_tools.TOOL_MAP` 擷取**完整**工具回傳（faithfulness 證據）；逐題記錄 token／成本／延遲；**每題落地存檔**（長跑可抗中斷）。 |
| `judge_eval.py` | 先做確定性檢查（經文連結 book/chap↔文字比對、「引文」須存在於工具證據、引用文章連結實際抓取＋摘錄），再由 `claude-opus-5` 評分。Judge 會被告知該引擎是否具備 web_search（不懲罰 v4–v6 沒有文章引用）。Judge 自身若因安全分類器 refuse（如答案點名資安工具），自動改用中性化題目＋`claude-opus-4-7` fallback。 |
| `quant_eval.py` | 確定性百分比評分（免費、離線、不需 judge）：引用佐證率、引文佐證率、共識召回率等。定義見 `README_METRICS.md`。 |
| `report_eval.py` | 多引擎並排：總分、逐類分數、確定性錯誤數、延遲中位數、**各引擎成本**與 judge 成本。 |
| `eval_pricing.py` | 引擎與 judge 的計費（含 v7 web_search 每千次 $10）。 |

## 成本與已知限制

- **成本**：單題無對話歷史時較便宜。2026-08-20 以舊的 50 題實測：引擎每版約
  $1.5–2.3、judge 每版約 $2.1–2.7。現行題庫 70 題，成本約再多四成
  （每版引擎約 $2–3、judge 約 $3–4）。有對話歷史的真實查詢會更貴。
- **歷史數字不可直接並排**：舊 run 檔是 50 題，且引用涵蓋率的分母已由
  「非 adversarial」改為 `expected_behavior` 判定，同一份舊檔重算會與
  `report_20260821_quant.md` 的數字略有出入（該報告的 44 → 47）。
- **確定性「引文檢查」有偽陽性**：引號樣式（「」vs『』）、跨節拼接、
  和合本 vs 雅威 用字差異都會被標為「未命中」，故 `unsupported quotes` 是
  **篩選訊號、非定論**——最終由 LLM judge 判定。
- **Judge 偏誤**：judge（Opus 5）比受測引擎（Sonnet 5）強且為不同模型，
  以降低 self-preference；但 LLM 評分本身仍有變異，重要結論宜看趨勢與逐題
  rationale，而非單一小數點差異。
- **單輪**：目前只評單輪問答；56 題多輪追問（如「那羅得的妻子呢？」）尚未納入。
