from __future__ import annotations

"""
claude_bible_rag_v2.py — Claude 4.7 × FHL Bible Tools (agentic RAG engine)
==========================================================================
v2: same as claude_bible_rag.py, plus deterministic post-processing that
turns verse citations in the final answer — e.g. (約翰福音 3:16) — into
Markdown hyperlinks to bible.fhl.net read.php.  URLs are built in Python
from the fhl_tools book table, so the LLM cannot hallucinate links.

Drop-in replacement for bible_rag.bible_query() that uses the Anthropic API
instead of a local Gemma model.  Same tool set (fhl_tools.py), same interface.

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

# ─────────────────────────────────────────────────────────────────────────────
# 1. SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

MODEL_ID        = "claude-opus-4-7"
MAX_TOOL_ROUNDS = 10
RESULT_PREVIEW  = 300

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
) -> str:
    """
    Run a full agentic Bible RAG query using Claude with Anthropic tool_use.

    Same interface as bible_rag.bible_query() — drop-in replacement.
    If log_callback is provided, it is called with (str) for each log line
    instead of printing.
    """
    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        elif verbose:
            print(msg)

    client = _get_client()

    tool_schemas = ANTHROPIC_TOOLS
    if tools is not None and tools is not ALL_TOOLS:
        active_names = {fn.__name__ for fn in tools}
        tool_schemas = [t for t in ANTHROPIC_TOOLS if t["name"] in active_names]

    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_question})

    api_kwargs = dict(
        model=MODEL_ID,
        max_tokens=16384,
        system=BIBLE_SYSTEM_PROMPT,
        tools=tool_schemas,
    )
    if temperature is not None:
        api_kwargs["temperature"] = temperature
    if top_p is not None:
        api_kwargs["top_p"] = top_p
    if top_k is not None:
        api_kwargs["top_k"] = top_k

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

        if response.stop_reason != "tool_use":
            if stream_callback:
                full_text = "".join(accumulated)
            else:
                full_text = "\n".join(b.text for b in response.content if b.type == "text")
            _log(f"[Round {round_num}] ✓ Final answer ({elapsed:.1f}s, {len(full_text)} chars)")
            return linkify_bible_references(full_text)

        _log(f"[Round {round_num}] ✓ Tool calls ({elapsed:.1f}s)")
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in tool_use_blocks:
            name = block.name
            args = block.input

            args_str = json.dumps(args, ensure_ascii=False)
            _log(f"[Round {round_num}] 🔧 {name}({args_str})")

            if name not in TOOL_MAP:
                result = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = TOOL_MAP[name](**args)
                except TypeError as e:
                    result = {"error": f"Bad arguments for {name}: {e}"}

            result_json = json.dumps(result, ensure_ascii=False)

            preview = (result_json[:RESULT_PREVIEW] + "..."
                       if len(result_json) > RESULT_PREVIEW else result_json)
            _log(f"  → {preview}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_json,
            })

        messages.append({"role": "user", "content": tool_results})

    _log(f"[Max rounds {MAX_TOOL_ROUNDS} reached] Generating final answer.")

    messages.append({
        "role": "user",
        "content": "You have reached the maximum number of tool rounds. Please synthesize all the data you have gathered and provide your final answer now.",
    })

    if stream_callback:
        accumulated = []
        with client.messages.stream(**api_kwargs, messages=messages) as stream:
            for chunk in stream.text_stream:
                accumulated.append(chunk)
                stream_callback(chunk)
        return linkify_bible_references("".join(accumulated))

    response = client.messages.create(**api_kwargs, messages=messages)
    return linkify_bible_references(
        "\n".join(b.text for b in response.content if b.type == "text")
    )
