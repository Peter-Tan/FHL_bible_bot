from __future__ import annotations

"""
repair_usage_cost.py — one-off repair of usage_log.cost_usd in chat.db.

    .venv/bin/python scripts/repair_usage_cost.py            # dry run
    .venv/bin/python scripts/repair_usage_cost.py --apply    # write

Why: Sonnet 5 launched at $2/$10 per MTok, announced as introductory with a
rise to $3/$15 on 2026-09-01. That rise was cancelled and $2/$10 became the
standard price, but server/chat.py switched on the date anyway — so every
claude-sonnet-5 row logged from 2026-09-01 until the fix (a9fe8a2,
2026-10-04) was priced 50% too high, inflating the 用量統計 totals.

Each row is re-priced from its own stored token counts rather than scaled by
2/3. usage_log does not store the web_search count, so whatever the stored cost
holds beyond the old-rate token cost (v7 searches at $0.01 each; zero for
production v6.1) is carried over unchanged. A row is only touched when its
stored cost matches the old $3/$15 pricing — an already-repaired row no longer
does — which makes the script safe to run more than once.

created_at is local time, the same clock the old date.today() switch used.

Backs up chat.db (via the SQLite backup API, so WAL content is included)
before writing.
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.chat import PRICE_PER_MTOK, WEB_SEARCH_PRICE_PER_QUERY  # noqa: E402

DB_PATH = ROOT / "logs" / "chat.db"
MODEL = "claude-sonnet-5"
WRONG_FROM = "2026-09-01"
# The rate the old code wrongly applied from WRONG_FROM on.
OLD_STANDARD = {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}
EPS = 1e-6


def token_cost(row: sqlite3.Row, price: dict) -> float:
    return (
        row["input_tokens"] * price["input"]
        + row["output_tokens"] * price["output"]
        + row["cache_write_tokens"] * price["cache_write"]
        + row["cache_read_tokens"] * price["cache_read"]
    ) / 1_000_000


def overpriced_extra(row: sqlite3.Row) -> float | None:
    """Web-search cost carried in the row if it was priced at OLD_STANDARD,
    else None (already repaired, or priced some other way — leave it)."""
    extra = row["cost_usd"] - token_cost(row, OLD_STANDARD)
    searches = round(extra / WEB_SEARCH_PRICE_PER_QUERY)
    if searches < 0 or abs(extra - searches * WEB_SEARCH_PRICE_PER_QUERY) > EPS:
        return None
    return searches * WEB_SEARCH_PRICE_PER_QUERY


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-price claude-sonnet-5 usage_log rows overpriced since 2026-09-01.")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM usage_log WHERE model = ? AND created_at >= ? ORDER BY id",
        (MODEL, WRONG_FROM),
    ).fetchall()

    correct = PRICE_PER_MTOK[MODEL]
    fixes: list[tuple[float, int]] = []
    skipped = 0
    old_total = new_total = 0.0
    for row in rows:
        extra = overpriced_extra(row)
        if extra is None:
            skipped += 1
            continue
        new_cost = token_cost(row, correct) + extra
        fixes.append((new_cost, row["id"]))
        old_total += row["cost_usd"]
        new_total += new_cost

    print(f"{MODEL} rows since {WRONG_FROM}: {len(rows)}")
    print(f"  to repair: {len(fixes)}   skipped (not at old $3/$15 pricing): {skipped}")
    print(f"  cost_usd:  ${old_total:.4f} → ${new_total:.4f}  (−${old_total - new_total:.4f})")

    if not fixes:
        return
    if not args.apply:
        print("dry run — rerun with --apply to write")
        return

    backup = DB_PATH.with_name(f"chat.db.bak-{datetime.now():%Y%m%d-%H%M%S}")
    with sqlite3.connect(backup) as dst:
        conn.backup(dst)
    print(f"backup: {backup}")

    with conn:
        conn.executemany("UPDATE usage_log SET cost_usd = ? WHERE id = ?", fixes)
    print(f"updated {len(fixes)} row(s)")


if __name__ == "__main__":
    main()
