"""Shared pricing for the eval suite.

Mirrors server/chat.py's constants (kept separate so the eval never imports
FastAPI code). Engine runs are priced by the model recorded in usage; the
judge is priced at Claude Opus 5 rates.
"""
# USD per million tokens: (input, output, cache_write, cache_read)
# Sonnet 5's announced 2026-09-01 rise to $3/$15 was cancelled; Sonnet 5.5
# launched at the same $2/$10.
ENGINE_PRICES = {
    "claude-sonnet-5":   (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
}
JUDGE_PRICE = (5.00, 25.00, 6.25, 0.50)  # claude-opus-5

WEB_SEARCH_PER_QUERY = 10.00 / 1_000


def _token_cost(usage: dict, price) -> float:
    inp, out, cw, cr = price
    return (
        usage.get("uncached_in", 0) * inp
        + usage.get("out", 0) * out
        + usage.get("cache_write", 0) * cw
        + usage.get("cache_read", 0) * cr
    ) / 1_000_000


def engine_cost_usd(usage: dict) -> float:
    """Cost of one engine query from its usage dict (all engines v4-v8)."""
    if not usage:
        return 0.0
    model = usage.get("model", "claude-sonnet-5")
    # v8 serves Gemma locally — free. Without this the fallback below would
    # price it at Sonnet rates and make the report's cost column meaningless.
    if str(model).startswith("gemma-"):
        return 0.0
    # Unknown model (FHL_V4_MODEL_ID override): fall back to Sonnet 5.5 rates.
    price = ENGINE_PRICES.get(model, ENGINE_PRICES["claude-sonnet-5-5"])
    return (_token_cost(usage, price)
            + usage.get("web_search", 0) * WEB_SEARCH_PER_QUERY)


def judge_cost_usd(usage: dict) -> float:
    return _token_cost(usage, JUDGE_PRICE)
