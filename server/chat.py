from __future__ import annotations

"""POST /api/chat — runs bible_query() in a worker thread, streams SSE."""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import db

# The RAG engine lives in scripts/ and is imported unchanged.
# v4 = Sonnet 5 + style parameter (v3 stays with the production Gradio app).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from claude_bible_rag_v4 import STYLE_INSTRUCTIONS, bible_query  # noqa: E402
from fhl_tools import ALL_TOOLS  # noqa: E402

router = APIRouter(prefix="/api")

MAX_CONCURRENT_QUERIES = int(os.environ.get("FHL_MAX_CONCURRENT", "10"))
_active_queries = 0  # mutated only on the event loop — no lock needed

# Claude Sonnet 5 pricing, USD per million tokens. Introductory pricing
# ($2/$10) applies through 2026-08-31, standard ($3/$15) after. Cache writes
# cost 1.25x the input rate, cache reads 0.1x. Cost is computed at query time
# with the rate in effect that day, so stored rows stay historically accurate.
SONNET5_INTRO_UNTIL = "2026-08-31"
PRICE_PER_MTOK_INTRO = {
    "input": 2.00,
    "output": 10.00,
    "cache_write": 2.50,
    "cache_read": 0.20,
}
PRICE_PER_MTOK_STANDARD = {
    "input": 3.00,
    "output": 15.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
}


def _estimate_cost_usd(usage: dict) -> float:
    from datetime import date

    price = (
        PRICE_PER_MTOK_INTRO
        if date.today().isoformat() <= SONNET5_INTRO_UNTIL
        else PRICE_PER_MTOK_STANDARD
    )
    return (
        usage.get("uncached_in", 0) * price["input"]
        + usage.get("out", 0) * price["output"]
        + usage.get("cache_write", 0) * price["cache_write"]
        + usage.get("cache_read", 0) * price["cache_read"]
    ) / 1_000_000


def _log_usage(user_id: str, conv_id: str, usage: dict) -> None:
    """Persist one query's token usage; never let accounting break the chat."""
    if not usage:
        return
    try:
        db.log_usage(
            user_id=user_id,
            conversation_id=conv_id,
            model=usage.get("model", ""),
            input_tokens=usage.get("uncached_in", 0),
            output_tokens=usage.get("out", 0),
            cache_read_tokens=usage.get("cache_read", 0),
            cache_write_tokens=usage.get("cache_write", 0),
            cost_usd=_estimate_cost_usd(usage),
        )
    except Exception:
        pass


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    style: str = "brief"  # "brief" | "comprehensive"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    global _active_queries

    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")
    if body.style not in STYLE_INSTRUCTIONS:
        raise HTTPException(status_code=400, detail="Invalid style")
    if not db.conversation_owned(request.state.user_id, body.conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if _active_queries >= MAX_CONCURRENT_QUERIES:
        raise HTTPException(status_code=429, detail="Server busy, try again later")

    conv_id = body.conversation_id
    user_id = request.state.user_id
    history = db.get_api_history(conv_id)

    async def event_stream():
        global _active_queries
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        tool_lines: list[str] = []  # written and read only in the worker thread

        def on_log(line: str) -> None:
            tool_lines.append(line)
            loop.call_soon_threadsafe(queue.put_nowait, ("tool_log", {"line": line}))

        def on_stream(chunk: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("text_delta", {"text": chunk}))

        def worker() -> None:
            # Persisting happens HERE, not in the generator: if the browser
            # disconnects (tab closed, conversation switched) the generator is
            # cancelled, but the thread runs to completion and the turn is
            # still saved — the user finds the answer when they come back.
            usage: dict = {}  # filled in-place by bible_query after each round
            try:
                answer = bible_query(
                    user_question=text,
                    tools=ALL_TOOLS,
                    history=history if history else None,
                    verbose=False,
                    log_callback=on_log,
                    stream_callback=on_stream,
                    style=body.style,
                    usage_out=usage,
                ) or ""
                _log_usage(user_id, conv_id, usage)
                tool_log = "\n".join(tool_lines) if tool_lines else None
                message_id, title = db.append_turn(conv_id, text, answer, tool_log)
                # `content` is the final post-processed answer (verse citations
                # linkified) — the streamed deltas were raw, so the client
                # swaps in this version.
                loop.call_soon_threadsafe(queue.put_nowait, ("__done__", {
                    "message_id": message_id,
                    "title": title,
                    "content": answer,
                }))
            except Exception as exc:  # surface RAG errors as an SSE event
                # Tokens consumed before the failure are still billed — log them.
                _log_usage(user_id, conv_id, usage)
                loop.call_soon_threadsafe(queue.put_nowait, ("__error__", str(exc)))

        def _release(_future) -> None:
            # add_done_callback runs on the event loop, so plain decrement is
            # safe. Tied to the worker (not the generator) so the slot stays
            # held while a disconnected query keeps running in the background.
            global _active_queries
            _active_queries -= 1

        _active_queries += 1
        loop.run_in_executor(None, worker).add_done_callback(_release)
        while True:
            kind, payload = await queue.get()
            if kind == "__error__":
                yield _sse("error", {"detail": payload})
                return
            if kind == "__done__":
                yield _sse("done", payload)
                return
            yield _sse(kind, payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )
