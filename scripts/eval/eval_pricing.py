"""Shared pricing for the eval suite.

Mirrors server/chat.py's constants (kept separate so the eval never imports
FastAPI code). Engine runs are priced by the model recorded in usage; the
judge is priced at Claude Opus 5 rates.
"""
from datetime import date

SONNET5_INTRO_UNTIL = "2026-08-31"

# USD per million tokens: (input, output, cache_write, cache_read)
ENGINE_PRICES = {
    "claude-sonnet-5-intro":    (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5-standard": (3.00, 15.00, 3.75, 0.30),
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
    """Cost of one engine query from its usage dict (all engines v4-v7)."""
    if not usage:
        return 0.0
    model = usage.get("model", "claude-sonnet-5")
    if model == "claude-sonnet-5":
        key = ("claude-sonnet-5-intro"
               if date.today().isoformat() <= SONNET5_INTRO_UNTIL
               else "claude-sonnet-5-standard")
        price = ENGINE_PRICES[key]
    else:
        # Unknown model (FHL_V4_MODEL_ID override): fall back to standard
        # Sonnet rates and flag it so the report can warn.
        price = ENGINE_PRICES["claude-sonnet-5-standard"]
    return (_token_cost(usage, price)
            + usage.get("web_search", 0) * WEB_SEARCH_PER_QUERY)


def judge_cost_usd(usage: dict) -> float:
    return _token_cost(usage, JUDGE_PRICE)
