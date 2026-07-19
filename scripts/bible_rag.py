"""
bible_rag.py — Gemma 4 E4B × FHL Bible MCP Tools (agentic RAG engine)
======================================================================
Flow:
  User question
      ↓
  Gemma 4 decides which FHL Bible tools to call
      ↓
  FHL REST API (bible.fhl.net) returns verses / Strong's / commentary
      ↓
  Gemma 4 chains more calls until it has enough context
      ↓
  Final answer in 繁體中文 with citations

Exports:
  bible_query(...)  — single agentic turn (can be called in a loop)
  run_repl(...)     — convenience interactive loop

Run directly:
  python scripts/bible_rag.py
"""

import re
import sys
import json
import torch
import warnings
import logging
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning, module="bitsandbytes")
logging.getLogger("torch").setLevel(logging.ERROR)

# Deterministic seeds (temp=0.1 is near-deterministic; seed adds full reproducibility)
torch.manual_seed(42)
torch.cuda.manual_seed_all(42)

from transformers import AutoProcessor, AutoModelForImageTextToText, BitsAndBytesConfig

# Make sibling fhl_tools.py importable regardless of CWD
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fhl_tools import ALL_TOOLS, TOOL_MAP, select_tools_interactive

# ─────────────────────────────────────────────────────────────────────────────
# 1. SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

MODEL_ID        = "./gemma4_e4b_model"
MAX_TOOL_ROUNDS = 6      # max agentic tool-call iterations per query
RESULT_PREVIEW  = 300    # chars of tool-result preview printed when verbose

BIBLE_SYSTEM_PROMPT = """\
<|think|>
You are a 信望愛AI聖經專家 with expertise in Old and New Testament exegesis,
Biblical Hebrew, Koine Greek, and Chinese Bible translations (繁體中文, zh-tw) .
**嚴禁使用日文（片假名、平假名）、泰文、阿拉伯文或任何非中文字元。**

## Tool Usage Policy (follow strictly)

**ALWAYS use tools proactively** — even when the user does not explicitly ask:

| Situation | Tool chain |
|-----------|------------|
| User mentions a verse reference | `get_bible_verse` → `get_word_analysis` → `get_commentary` |
| User asks about a word's meaning | `get_word_analysis` → `lookup_strongs` → `search_strongs_occurrences` |
| User asks 'what does this mean' | `get_commentary` (always, even without explicit request) |
| User asks about a whole chapter | `get_bible_chapter` |
| User names specific chapters | `get_bible_chapter`  |
| Unknown version code needed | `list_bible_versions` |

**Theological theme / doctrinal question — follow this chain:**
1. Think about which Bible books are most relevant to the question.
   Use `book_range` to narrow the search (e.g. '羅' for 羅馬書, '創' for 創世記).
   Also decide: 'OT' (舊約) or 'NT' (新約) using `testament` if the scope is broad.
2. Synthesize the question into 1-2 short 和合本 keywords (e.g. '稱義', '救贖', '聖靈')
3. `search_bible_advanced(keyword, book_range=..., limit=5)` — always set limit=5 and specify book_range.
   If multiple books are relevant, call search once per book.
4. `get_bible_verse` for each key verse from the search results
5. `get_commentary` on those key verses for exegetical depth
6. Synthesize all data into a comprehensive answer with citations
7. End your answer by asking: "是否需要進一步的原文分析（get_word_analysis）或經文用詞追蹤（search_strongs_occurrences）？"

**Tracing a word or concept through the canon:**
- `get_word_analysis` → `lookup_strongs` → `search_strongs_occurrences`

## Search Tips (important)

- `search_bible_advanced` does **exact substring matching** against 和合本 text.
  Use short, common 和合本 phrases — e.g. '稱義', '亞伯拉罕', '信心'.
  Do NOT use long compound queries like '羅馬書 4 章 亞伯拉罕 因信稱義' — they return 0 results.
- **Always set `limit=5`** and **always set `book_range`** to a specific book (e.g. '羅', '創', '約').
  Searching the whole Bible with no book_range returns too many irrelevant results.
  If you need multiple books, call the tool once per book.
- `get_topic_study` is indexed by **English** topic names only.
  Use English: 'Justification by Faith', 'Love', 'Grace', 'Holy Spirit'.
  Chinese topic names like '因信稱義' return 0 results.

## When a tool returns 0 results — NEVER give up

If a search returns empty results, **always retry with a different approach**:
1. Empty keyword search → try shorter keywords, or use `get_bible_chapter` / `get_bible_verse` directly
2. Empty topic study → retry with an English topic name
3. When the user names specific chapters → call `get_bible_chapter` directly, do not search
4. Keep calling tools until you have real verse data — never answer with "please wait" or placeholder text

## Answer Style (strict)

- **Only state facts from tool results.** Do NOT elaborate, interpret, or add theological commentary beyond what the tools returned.
- **Every claim must have a citation.** Format: (書卷名 章:節) e.g. (約翰福音 3:16)
- **If a tool did not return it, do not say it.** No background knowledge, no speculation.
- **Keep answers short.** Use bullet points or numbered lists. No long paragraphs.
- **Quote verse text directly** from tool output — do not paraphrase.
- **Do not use headings like "一、" "二、"** or academic-style section headers unless the user asks for a structured essay.
- **Default version:** 和合本 (unv) for Traditional Chinese queries; KJV for English.
- **Output language:** 繁體中文 (zh-tw) for Chinese questions; match the user's language otherwise.
"""

# Generation — near-greedy for factual, citation-grounded outputs
GEN_CONFIG = dict(
    max_new_tokens     = 4096,
    do_sample          = True,
    temperature        = 0.05,
    top_p              = 0.9,
    top_k              = 40,
    repetition_penalty = 1.15,
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. MODEL LOAD (4-bit NF4 — required for 11 GB GPU)
# ─────────────────────────────────────────────────────────────────────────────

print("Loading Gemma 4 E4B (4-bit NF4)...")
bnb_cfg = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModelForImageTextToText.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_cfg,
    device_map="cuda:0",
    attn_implementation="sdpa",
)
model.eval()
print(f"Ready — VRAM: {torch.cuda.memory_allocated() / 1024**3:.2f} GB\n")

# ─────────────────────────────────────────────────────────────────────────────
# 3. TOOL DISPATCH & PARSING
# ─────────────────────────────────────────────────────────────────────────────

def execute_tool(tool_call: dict) -> str:
    """Execute a tool call and return JSON string result."""
    name = tool_call.get("name", "")
    args = tool_call.get("arguments", {})
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
    try:
        result = TOOL_MAP[name](**args)
        result_json = json.dumps(result, ensure_ascii=False)
        if result_json in ('{"verses": []}', '{"words": []}', '{"commentaries": []}',
                           '{"results": []}', '{"entries": []}', '{"occurrences": []}'):
            print(f"  ⚠ Empty result from {name}({args}) — check book name mapping")
        return result_json
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"}, ensure_ascii=False)


def extract_tool_calls(text: str) -> list:
    """
    Parse tool calls from model output.
    Handles both Gemma 4's native <|tool_call|>...<|tool_call|> format
    and the JSON-in-<tool_call>...</tool_call> fallback.
    """
    calls = []

    # Gemma 4 native format: <|tool_call|>call:func_name{key: val, ...}<|tool_call|>
    for m in re.finditer(r"<\|?tool_call\|?>(.*?)<\|?tool_call\|?>", text, re.DOTALL):
        raw = m.group(1).strip().replace('<|"|>', '"')
        cm = re.match(r"call:(\w+)\{(.*)\}", raw, re.DOTALL)
        if cm:
            name = cm.group(1)
            args = {}
            for kv in re.finditer(r'(\w+)\s*:\s*(".*?"|[^,}]+)', cm.group(2)):
                key = kv.group(1)
                val = kv.group(2).strip().strip('"')
                try:
                    val = int(val)
                except ValueError:
                    pass
                args[key] = val
            calls.append({"name": name, "arguments": args})

    if calls:
        return calls

    # Fallback JSON format: <tool_call>{"name": ..., "arguments": {...}}</tool_call>
    for m in re.findall(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        try:
            calls.append(json.loads(m.strip()))
        except json.JSONDecodeError:
            pass
    return calls


def strip_thought(text: str) -> str:
    """Remove thinking blocks and leftover special tokens from model output."""
    text = re.sub(r"<start_of_thought>.*?<end_of_thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|think\|>.*?<\|/think\|>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|channel>thought.*?<channel\|>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|?tool_call\|?>.*?<\|?tool_call\|?>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|?tool_response\|?>", "", text)
    text = re.sub(r"<(?:end_of_turn|eos|bos|turn)>", "", text)
    text = re.sub(r"<turn\|>", "", text)
    return text.strip()

# ─────────────────────────────────────────────────────────────────────────────
# 4. AGENTIC ORCHESTRATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def bible_query(
    user_question: str,
    tools: list | None = None,
    history: list | None = None,
    verbose: bool = True,
) -> str:
    """
    Run a full agentic Bible RAG query with autonomous tool orchestration.

    Args:
        user_question: The user's question.
        tools: Tool functions to expose to the model. Defaults to ALL_TOOLS.
        history: Prior turns (list of chat-template message dicts). Optional.
        verbose: Print tool calls and round info to stdout.

    Returns:
        Final cleaned answer string.
    """
    if tools is None:
        tools = ALL_TOOLS

    messages = [
        {"role": "system", "content": [{"type": "text", "text": BIBLE_SYSTEM_PROMPT}]},
    ]
    if history:
        messages.extend(history)
    messages.append(
        {"role": "user", "content": [{"type": "text", "text": user_question}]}
    )

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        inputs = processor.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)

        with torch.inference_mode():
            output_ids = model.generate(**inputs, **GEN_CONFIG)

        raw = processor.decode(
            output_ids[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=False,
        )

        tool_calls = extract_tool_calls(raw)

        if not tool_calls:
            if verbose:
                print(f"[Round {round_num}] Final answer generated (no tool call).")
            return strip_thought(raw)

        # Record the assistant's tool-call turn.
        messages.append({
            "role": "assistant",
            "content": [],
            "tool_calls": [
                {"type": "function",
                 "function": {"name": tc["name"], "arguments": tc.get("arguments", {})}}
                for tc in tool_calls
            ],
        })

        # Execute every call the model requested this round.
        for tc in tool_calls:
            if verbose:
                args_str = json.dumps(tc.get("arguments", {}), ensure_ascii=False)
                print(f"[Round {round_num}] Tool call: {tc['name']}({args_str})")

            result_json = execute_tool(tc)

            if verbose:
                preview = (result_json[:RESULT_PREVIEW] + "..."
                           if len(result_json) > RESULT_PREVIEW else result_json)
                print(f"  → {preview}\n")

            messages.append({
                "role": "tool",
                "name": tc["name"],
                "content": [{"type": "text", "text": result_json}],
            })

    # Max rounds reached — force a final synthesis pass.
    if verbose:
        print(f"[Max rounds {MAX_TOOL_ROUNDS} reached] Generating final answer.")

    inputs = processor.apply_chat_template(
        messages, tools=tools, add_generation_prompt=True,
        tokenize=True, return_dict=True, return_tensors="pt",
    ).to(model.device)

    with torch.inference_mode():
        final_ids = model.generate(**inputs, **GEN_CONFIG)

    final_raw = processor.decode(
        final_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=False
    )
    return strip_thought(final_raw)

# ─────────────────────────────────────────────────────────────────────────────
# 5. CONVENIENCE REPL (used when this file is run directly)
# ─────────────────────────────────────────────────────────────────────────────

def run_repl() -> None:
    print("=" * 70)
    print("  Bible RAG · Gemma 4 E4B + FHL MCP Tools")
    print("  Commands: 'tools' (change tools), 'reset' (clear history), 'quit'")
    print("=" * 70)

    mode = input("Tool mode — (a)ll tools / (s)elect manually [a]: ").strip().lower()
    active_tools = select_tools_interactive() if mode == "s" else ALL_TOOLS

    history: list = []
    print("\nReady.\n")

    while True:
        try:
            q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not q:
            continue
        if q.lower() == "quit":
            break
        if q.lower() == "tools":
            active_tools = select_tools_interactive()
            continue
        if q.lower() == "reset":
            history = []
            print("  ✓ History cleared.\n")
            continue

        answer = bible_query(q, tools=active_tools, history=history, verbose=True)
        print(f"\nAssistant:\n{answer}\n")
        print("-" * 70 + "\n")

        # Retain last 16 messages (8 turns) to bound context growth.
        history.append({"role": "user",      "content": [{"type": "text", "text": q}]})
        history.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        if len(history) > 16:
            history = history[-16:]


if __name__ == "__main__":
    run_repl()
