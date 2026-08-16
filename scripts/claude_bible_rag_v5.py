from __future__ import annotations

"""
claude_bible_rag_v5.py — Claude Sonnet 5 × FHL Bible Tools (agentic RAG engine)
===============================================================================
Drop-in replacement for bible_rag.bible_query() that uses the Anthropic API
instead of a local Gemma model.  Same tool set (fhl_tools.py), same interface.

v5 (this file — used by the FastAPI/React UI; v4 kept unchanged as rollback):
  - Simplified-character cleanup on the final answer. A scan of
    logs/chat.db (2026-04-30 → 2026-08-13) found 8 of 288 answers with
    simplified characters mixed into otherwise correct 繁體 sentences
    (「核心问题」「强调」「银子作为在众人眼前证明」), despite the system prompt
    asking for 繁體中文 (zh-tw). zh_hant.to_traditional() now runs in
    _postprocess_answer() BEFORE linkification — order matters, because a
    simplified book name (马太福音) does not match the citation regex, so
    converting first also recovers links that were previously dropped.
    Narrow table, ~0.9 ms on the longest answer ever logged, and it runs
    after streaming has finished — no effect on time-to-first-token.
    See scripts/zh_hant.py for why plain OpenCC was rejected.

v4 (claude_bible_rag_v4.py — kept as rollback; first engine of the NEW
FastAPI/React UI, v3 stays in production under the Gradio app):
  - Default model: claude-sonnet-5 (A/B test 2026-07-02 vs claude-opus-4-7:
    ~20% faster wall time, better parallel tool batching — 2 rounds instead
    of 3 on multi-passage comparisons — comparable quality, ~half the cost).
    Sonnet 5 runs adaptive thinking by default when `thinking` is omitted.
  - Env override is FHL_V4_MODEL_ID (NOT FHL_MODEL_ID, which production v3
    pins to claude-opus-4-7 in .env — separate vars keep them independent).
  - New `style` parameter on bible_query(): "brief" (default) or
    "comprehensive". The instruction is injected as a SECOND system block
    placed AFTER the cache_control breakpoint, so both styles share one
    prompt cache (the cached prefix stays byte-identical).
  - Strong's number hyperlinks: the model is instructed to write Strong's
    codes as SNG#####/SNH##### (5-digit, FHL dictionary convention), and
    linkify_strongs_numbers() post-processes them into links to the
    dictionary viewer https://bible.fhl.net/new/s.php?N=<0|1>&k=<num>
    (N=0 Greek/NT, N=1 Hebrew/OT; same params as the sd.php API) — URL
    built in Python, same anti-hallucination strategy as verse links.

CHANGELOG (all changes since claude_bible_rag.py v1, as of 2026-07-02)
----------------------------------------------------------------------
v2 (claude_bible_rag_v2.py — kept as rollback):
  - Verse-citation hyperlinks: deterministic post-processing turns citations
    in the final answer — e.g. (約翰福音 3:16), (羅3：24), (羅馬書 8章),
    John 3:16 — into Markdown links to bible.fhl.net read.php.
    URLs are built in Python from the fhl_tools book table (live listall.html
    merged with the static fallback), so the LLM cannot hallucinate links.
  - Links always open the WHOLE chapter (no &sec= param) — even for a
    single-verse citation, per product decision.
  - Link params: VERSION1=unv, TABFLAG=1, strongflag=1.

v3 (this file — live version):
  - Prompt caching (Anthropic cache_control):
      * breakpoint on the system prompt → caches tools + system across
        rounds AND across queries (5-min TTL);
      * rolling breakpoint on the newest tool_result block → caches the
        growing conversation incrementally within a query.
    Effect: after warmup only ~300-500 tokens/round billed uncached.
  - Parallel FHL tool execution: all tool calls in a round run concurrently
    via ThreadPoolExecutor (3 HTTP calls ≈ 0.2s instead of the sum).
  - System prompt: "Batch your tool calls" section added — Claude requests
    multiple independent lookups in ONE round (fewer round-trips).
  - Per-query latency summary log line:
      [Summary] N round(s) | Claude Xs | tools Xs | output N tok |
                cache read/write/uncached tok in
    NOTE: 'write' = cache_creation_input_tokens (INPUT written to cache,
    billed 1.25x once), NOT output tokens.
  - temperature/top_p/top_k accepted but IGNORED (they 400 on Opus 4.7;
    logged as a warning if passed).
  - MODEL_ID overridable via FHL_MODEL_ID in .env (default claude-sonnet-4-6;
    production pins FHL_MODEL_ID=claude-opus-4-7 after A/B test showed
    Sonnet writes longer answers / uses more rounds, eating its speed edge).
  - search_bible_advanced limit relaxed 5 → 20 verses per book (prompt-level
    change; verified working, e.g. 12 hits for 稱義 in 羅馬書).

Deployment: systemd user service `fhl-bible-ui.service` (port 7861);
server/chat.py imports this module. Rollback = switch that import back to
claude_bible_rag_v4 and restart. (The Gradio app on port 7860 is a separate
service and still runs v3.)

Requires:
  pip install anthropic
  export ANTHROPIC_API_KEY=sk-ant-...

Exports:
  bible_query(...)  — single agentic turn (matches bible_rag.bible_query signature)
"""

import os
import re
import sys
import json
import time
import inspect
import logging
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import get_type_hints

os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    import anthropic
except ImportError:
    print("ERROR: 'anthropic' package not installed. Run: pip install anthropic")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fhl_tools import ALL_TOOLS, TOOL_MAP, _BOOK_TO_SHORT, _BOOK_FALLBACK
from zh_hant import to_traditional

# ─────────────────────────────────────────────────────────────────────────────
# 1. SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

# Override without code changes: set FHL_V4_MODEL_ID in .env.
# (Deliberately NOT FHL_MODEL_ID — that var belongs to production v3.)
MODEL_ID        = os.environ.get("FHL_V4_MODEL_ID", "claude-sonnet-5")
MAX_TOOL_ROUNDS = 10
RESULT_PREVIEW  = 300

# Style instructions — injected as a second system block AFTER the cache
# breakpoint so both styles share the same cached prefix.
STYLE_INSTRUCTIONS = {
    "brief": (
        "回答風格：精簡扼要。以條列重點為主，只回答問題核心，控制在簡短篇幅內。"
    ),
    "comprehensive": (
        "回答風格：詳盡完整（此指示優先於上方 Answer Style 中"
        "「Keep answers short」的規定）。除核心答案外，請包含："
        "原文分析（希伯來文／希臘文）、歷史與文學背景、"
        "相關經文對照、註釋要點，提供深入而完整的說明。"
    ),
}
DEFAULT_STYLE = "brief"

BIBLE_SYSTEM_PROMPT = """\
You are a 信望愛AI聖經專家 with expertise in Old and New Testament exegesis,
Biblical Hebrew, Koine Greek, and Chinese Bible translations (繁體中文, zh-tw).

## Tool Usage Policy (follow strictly)

**ALWAYS use tools proactively** — even when the user does not explicitly ask:

| Situation | Tool chain |
|-----------|------------|
| User mentions a verse reference | `get_bible_verse` → `get_word_analysis` → `get_commentary` |
| User asks about a word's meaning | `get_word_analysis` → `lookup_strongs` → `search_strongs_occurrences` |
| User asks 'what does this mean' | `get_commentary` (always, even without explicit request) |
| User asks about a whole chapter | `get_bible_chapter` |
| User names specific chapters | `get_bible_chapter` directly |
| Unknown version code needed | `list_bible_versions` |

**Theological theme / doctrinal question — follow this chain:**
1. Think about which Bible books are most relevant to the question.
   Use `book_range` to narrow the search (e.g. '羅' for 羅馬書, '創' for 創世記).
   Also decide: 'OT' (舊約) or 'NT' (新約) using `testament` if the scope is broad.
2. Synthesize the question into 1-2 short 和合本 keywords (e.g. '稱義', '救贖', '聖靈')
3. `search_bible_advanced(keyword, book_range=..., limit=20)` — always set limit=20 and specify book_range.
   If multiple books are relevant, call search once per book.
4. `get_bible_verse` for each key verse from the search results
5. `get_commentary` on those key verses for exegetical depth
6. Synthesize all data into a comprehensive answer with citations
7. End your answer by asking: "是否需要進一步的原文分析（get_word_analysis）或經文用詞追蹤（search_strongs_occurrences）？"

**Tracing a word or concept through the canon:**
- `get_word_analysis` → `lookup_strongs` → `search_strongs_occurrences`

## Batch your tool calls (important for speed)

When you need multiple independent lookups (several books, several verses,
verse + commentary), request them ALL in one response as multiple tool calls —
they execute in parallel. Do not request them one at a time across rounds.

## Search Tips (important)

- `search_bible_advanced` does **exact substring matching** against 和合本 text.
  Use short, common 和合本 phrases — e.g. '稱義', '亞伯拉罕', '信心'.
  Do NOT use long compound queries like '羅馬書 4 章 亞伯拉罕 因信稱義' — they return 0 results.
- **Always set `limit=20`** and **always set `book_range`** to a specific book (e.g. '羅', '創', '約').
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
- **Strong's numbers:** ALWAYS write them as `SN` + language letter + 5-digit
  zero-padded number: `SNG#####` for Greek/NT, `SNH#####` for Hebrew/OT —
  e.g. SNG00026 (ἀγάπη), SNH02617 (חֶסֶד). NEVER write G26, H2617,
  Strong's #26, or any other format. Write the plain code only — do NOT
  wrap it in a hyperlink yourself (links are added automatically).
"""

# ─────────────────────────────────────────────────────────────────────────────
# 2. AUTO-GENERATE ANTHROPIC TOOL SCHEMAS FROM FHL FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

_PY_TO_JSON_TYPE = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}


def _build_tool_schema(fn) -> dict:
    """Convert a Python function with docstring + type hints into an Anthropic tool schema."""
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    doc = inspect.getdoc(fn) or ""
    desc_lines = []
    for line in doc.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("args:") or stripped.lower().startswith("returns:"):
            break
        desc_lines.append(line)
    description = "\n".join(desc_lines).strip()

    properties = {}
    required = []
    for name, param in sig.parameters.items():
        hint = hints.get(name, str)
        hint_str = getattr(hint, "__name__", str(hint))
        if "Optional" in str(hint):
            inner = str(hint).replace("typing.Optional[", "").rstrip("]")
            json_type = _PY_TO_JSON_TYPE.get(inner, "string")
        else:
            json_type = _PY_TO_JSON_TYPE.get(hint_str, "string")

        prop: dict = {"type": json_type}

        param_doc = _extract_param_doc(doc, name)
        if param_doc:
            prop["description"] = param_doc

        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            if param.default is not None:
                prop["default"] = param.default

        properties[name] = prop

    schema: dict = {
        "name": fn.__name__,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
    return schema


def _extract_param_doc(docstring: str, param_name: str) -> str:
    """Extract a parameter's description from the Args: section of a docstring."""
    in_args = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if stripped.lower().startswith("returns:"):
            break
        if in_args and stripped.startswith(f"{param_name}:"):
            return stripped[len(param_name) + 1:].strip()
    return ""


ANTHROPIC_TOOLS = [_build_tool_schema(fn) for fn in ALL_TOOLS]

# ─────────────────────────────────────────────────────────────────────────────
# 3. VERSE-CITATION HYPERLINKS (deterministic post-processing — no LLM involved)
# ─────────────────────────────────────────────────────────────────────────────

FHL_READ_URL = "https://bible.fhl.net/new/read.php"
LINK_VERSION = "unv"

# Book-name lookup: live listall.html table merged with the static fallback,
# so both '1 Cor' (live) and '1Cor' (fallback) spellings resolve.
_LINK_BOOK_MAP = {k: v[1] for k, v in _BOOK_FALLBACK.items()}
_LINK_BOOK_MAP.update(_BOOK_TO_SHORT)

# Alternation sorted longest first so e.g. '約翰一書' wins over '約',
# '馬太福音' over '太'.
_BOOK_ALTERNATION = "|".join(
    re.escape(k) for k in sorted(_LINK_BOOK_MAP, key=len, reverse=True)
)

# Matches:  約翰福音 3:16 / 約3：16-18 / 羅馬書 8章 / John 3:16
# (?<!\[) skips text already inside a Markdown link.
_CITATION_RE = re.compile(
    rf"(?<!\[)"
    rf"({_BOOK_ALTERNATION})"          # 1: book name (any known form)
    rf"\s*第?\s*(\d{{1,3}})"           # 2: chapter
    rf"(?:"
    rf"\s*[:：]\s*(\d{{1,3}})"         # 3: verse
    rf"(?:\s*[-–~]\s*\d{{1,3}})?"      #    optional range end (kept in text, not URL)
    rf"|章"                            #    or chapter-only form '8章'
    rf")"
)


def _build_read_url(book_short: str, chap: str) -> str:
    # No 'sec' param: always open the whole chapter, even for a single-verse
    # citation like 約翰福音 3:16.
    return (f"{FHL_READ_URL}?chineses={quote(book_short)}&chap={chap}"
            f"&VERSION1={LINK_VERSION}&TABFLAG=1&strongflag=1")


def linkify_bible_references(text: str) -> str:
    """
    Wrap every recognised verse citation in a Markdown hyperlink to FHL read.php.

    The URL is built purely from the fhl_tools book table + regex captures,
    so links can never be hallucinated. Every link opens the whole chapter
    (e.g. 約翰福音 3:16 → John chapter 3). Unknown book names are left
    untouched.
    """
    def _repl(m: re.Match) -> str:
        book_short = _LINK_BOOK_MAP.get(m.group(1))
        if not book_short:
            return m.group(0)
        url = _build_read_url(book_short, m.group(2))
        return f"[{m.group(0)}]({url})"

    return _CITATION_RE.sub(_repl, text)


# Strong's codes as the model is instructed to write them (SNG00026 / SNH02617).
# Tolerates missing zero-padding; the guards skip codes already inside a
# markdown link (e.g. quoted FHL dictionary text).
_STRONGS_RE = re.compile(r"(?<!\[)\bSN([GH])0*(\d{1,5})\b(?!\]\()")


def linkify_strongs_numbers(text: str) -> str:
    """
    Wrap every Strong's code in a Markdown hyperlink to the FHL Strong's
    dictionary viewer page (new/s.php — human-readable; same N/k params as
    the sd.php API). Same anti-hallucination strategy as verse links: the
    URL is built purely in Python from the regex captures, never by the LLM.
    Params: N=0 → Greek (NT), N=1 → Hebrew (OT), k = bare number.
    """
    def _repl(m: re.Match) -> str:
        lang, num = m.group(1), int(m.group(2))
        canonical = f"SN{lang}{num:05d}"
        n_code = 0 if lang == "G" else 1
        url = f"https://bible.fhl.net/new/s.php?N={n_code}&k={num}"
        return f"[{canonical}]({url})"

    return _STRONGS_RE.sub(_repl, text)


def _postprocess_answer(text: str) -> str:
    """
    Post-process the final answer: simplified→Traditional, then verse links,
    then Strong's links.

    The conversion runs FIRST on purpose — 「马太福音 1:1」 does not match the
    citation regex (the book table is Traditional), so converting before
    linkifying also recovers verse links that a simplified slip would
    otherwise have cost us.
    """
    return linkify_strongs_numbers(linkify_bible_references(to_traditional(text)))


# ─────────────────────────────────────────────────────────────────────────────
# 4. CLIENT
# ─────────────────────────────────────────────────────────────────────────────

_client = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
            print("Get your key at: https://console.anthropic.com/settings/keys")
            sys.exit(1)
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# 5. AGENTIC ORCHESTRATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def bible_query(
    user_question: str,
    tools: list | None = None,
    history: list | None = None,
    verbose: bool = True,
    log_callback=None,
    stream_callback=None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    style: str = DEFAULT_STYLE,
    usage_out: dict | None = None,
) -> str:
    """
    Run a full agentic Bible RAG query using Claude with Anthropic tool_use.

    Same interface as bible_rag.bible_query() — drop-in replacement.
    If log_callback is provided, it is called with (str) for each log line
    instead of printing.

    style: "brief" (default) or "comprehensive" — controls answer length via
    a system block injected after the cache breakpoint. Unknown values fall
    back to the default.

    usage_out: optional dict the caller owns; kept in sync with cumulative
    token usage after every API round (keys: model, uncached_in, out,
    cache_read, cache_write). Updated in-place so totals survive even if a
    later round raises.

    Note: temperature/top_p/top_k are accepted for interface compatibility
    but ignored — Sonnet 5 rejects non-default values with a 400 error.
    """
    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        elif verbose:
            print(msg)

    if temperature is not None or top_p is not None or top_k is not None:
        _log("⚠ temperature/top_p/top_k are not supported on this model — ignored.")

    client = _get_client()

    tool_schemas = ANTHROPIC_TOOLS
    if tools is not None and tools is not ALL_TOOLS:
        active_names = {fn.__name__ for fn in tools}
        tool_schemas = [t for t in ANTHROPIC_TOOLS if t["name"] in active_names]

    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_question})

    # Prompt caching: breakpoint on the system prompt caches tools + system
    # (they render first) across rounds AND across queries. A second, rolling
    # breakpoint on the newest tool_result block (see below) caches the
    # growing conversation incrementally within a query.
    # The style block sits AFTER the breakpoint: it varies per request but
    # never invalidates the cached tools+system prefix.
    style_text = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS[DEFAULT_STYLE])
    api_kwargs = dict(
        model=MODEL_ID,
        max_tokens=16384,
        system=[
            {
                "type": "text",
                "text": BIBLE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": style_text},
        ],
        tools=tool_schemas,
    )

    # Latency accounting
    stats = {"claude_s": 0.0, "tools_s": 0.0,
             "cache_read": 0, "cache_write": 0, "uncached_in": 0, "out": 0}

    def _track(response):
        u = response.usage
        stats["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        stats["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        stats["uncached_in"] += u.input_tokens
        stats["out"] += u.output_tokens
        if usage_out is not None:
            usage_out["model"] = MODEL_ID
            usage_out.update(stats)

    def _log_summary(rounds: int):
        _log(f"[Summary] {rounds} round(s) | Claude {stats['claude_s']:.1f}s | "
             f"tools {stats['tools_s']:.1f}s | output {stats['out']} tok | "
             f"cache read {stats['cache_read']}, write {stats['cache_write']}, "
             f"uncached {stats['uncached_in']} tok in")

    def _strip_rolling_cache_marker():
        """Remove cache_control from previous tool_result blocks (max 4
        breakpoints per request — keep only system + the newest one)."""
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                for blk in msg["content"]:
                    if isinstance(blk, dict):
                        blk.pop("cache_control", None)

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        t0 = time.time()
        _log(f"[Round {round_num}] Calling Claude...")

        if stream_callback:
            accumulated: list[str] = []
            with client.messages.stream(**api_kwargs, messages=messages) as stream:
                for chunk in stream.text_stream:
                    accumulated.append(chunk)
                    stream_callback(chunk)
                response = stream.get_final_message()
        else:
            response = client.messages.create(**api_kwargs, messages=messages)

        elapsed = time.time() - t0
        stats["claude_s"] += elapsed
        _track(response)

        if response.stop_reason != "tool_use":
            if stream_callback:
                full_text = "".join(accumulated)
            else:
                full_text = "\n".join(b.text for b in response.content if b.type == "text")
            _log(f"[Round {round_num}] ✓ Final answer ({elapsed:.1f}s, {len(full_text)} chars)")
            _log_summary(round_num)
            return _postprocess_answer(full_text)

        _log(f"[Round {round_num}] ✓ Tool calls ({elapsed:.1f}s)")
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        messages.append({"role": "assistant", "content": response.content})

        def _run_tool(block):
            name = block.name
            args = block.input
            if name not in TOOL_MAP:
                return {"error": f"Unknown tool: {name}"}
            try:
                return TOOL_MAP[name](**args)
            except TypeError as e:
                return {"error": f"Bad arguments for {name}: {e}"}

        for block in tool_use_blocks:
            args_str = json.dumps(block.input, ensure_ascii=False)
            _log(f"[Round {round_num}] 🔧 {block.name}({args_str})")

        # Execute all tool calls of this round in parallel (FHL HTTP I/O bound)
        t_tools = time.time()
        with ThreadPoolExecutor(max_workers=min(8, len(tool_use_blocks))) as pool:
            results = list(pool.map(_run_tool, tool_use_blocks))
        stats["tools_s"] += time.time() - t_tools

        tool_results = []
        for block, result in zip(tool_use_blocks, results):
            result_json = json.dumps(result, ensure_ascii=False)

            preview = (result_json[:RESULT_PREVIEW] + "..."
                       if len(result_json) > RESULT_PREVIEW else result_json)
            _log(f"  → {preview}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_json,
            })

        # Rolling cache breakpoint: move it to the newest tool_result so the
        # whole conversation so far is served from cache next round.
        _strip_rolling_cache_marker()
        tool_results[-1]["cache_control"] = {"type": "ephemeral"}

        messages.append({"role": "user", "content": tool_results})

    _log(f"[Max rounds {MAX_TOOL_ROUNDS} reached] Generating final answer.")

    messages.append({
        "role": "user",
        "content": "You have reached the maximum number of tool rounds. Please synthesize all the data you have gathered and provide your final answer now.",
    })

    t0 = time.time()
    if stream_callback:
        accumulated = []
        with client.messages.stream(**api_kwargs, messages=messages) as stream:
            for chunk in stream.text_stream:
                accumulated.append(chunk)
                stream_callback(chunk)
            response = stream.get_final_message()
        stats["claude_s"] += time.time() - t0
        _track(response)
        _log_summary(MAX_TOOL_ROUNDS + 1)
        return _postprocess_answer("".join(accumulated))

    response = client.messages.create(**api_kwargs, messages=messages)
    stats["claude_s"] += time.time() - t0
    _track(response)
    _log_summary(MAX_TOOL_ROUNDS + 1)
    return _postprocess_answer(
        "\n".join(b.text for b in response.content if b.type == "text")
    )
