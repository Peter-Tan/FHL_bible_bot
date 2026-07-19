from __future__ import annotations

"""SQLite access layer for the chat backend (logs/chat.db, WAL mode)."""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "logs" / "chat.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    tool_log        TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    user_id    TEXT NOT NULL,
    action     TEXT NOT NULL,   -- 'copy' | 'good' | 'bad' | 'comment'
    comment    TEXT,            -- only for action='comment'
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id, id);
-- Per-query token/cost accounting. Separate from messages so usage totals
-- survive conversation deletion.
CREATE TABLE IF NOT EXISTS usage_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            TEXT NOT NULL,
    conversation_id    TEXT,
    model              TEXT,
    input_tokens       INTEGER NOT NULL DEFAULT 0,  -- uncached input
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_log(user_id, id);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _connect():
    # One short-lived connection per operation: safe across FastAPI's
    # threadpool workers; WAL keeps readers unblocked during writes.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


# ── users ─────────────────────────────────────────────────────────────────────

def user_exists(user_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        return row is not None


def create_user(user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)",
            (user_id, _now()),
        )


# ── conversations ─────────────────────────────────────────────────────────────

def list_conversations(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM conversations"
            " WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_conversation(user_id: str) -> dict:
    conv_id = str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
            " VALUES (?, ?, 'New chat', ?, ?)",
            (conv_id, user_id, now, now),
        )
    return {"id": conv_id, "title": "New chat", "updated_at": now}


def get_conversation(user_id: str, conv_id: str) -> dict | None:
    with _connect() as conn:
        conv = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations"
            " WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
        if conv is None:
            return None
        msgs = conn.execute(
            "SELECT id, role, content, tool_log, created_at FROM messages"
            " WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
        # Latest good/bad vote per message, so the UI can restore icon state.
        ratings = {
            r["message_id"]: r["action"]
            for r in conn.execute(
                "SELECT message_id, action FROM feedback"
                " WHERE action IN ('good','bad')"
                "   AND message_id IN"
                "   (SELECT id FROM messages WHERE conversation_id = ?)"
                " ORDER BY id",
                (conv_id,),
            ).fetchall()
        }
        result = dict(conv)
        result["messages"] = [
            dict(m, rating=ratings.get(m["id"])) for m in msgs
        ]
        return result


def conversation_owned(user_id: str, conv_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
        return row is not None


def delete_conversation(user_id: str, conv_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return True


# ── messages ──────────────────────────────────────────────────────────────────

def get_api_history(conv_id: str) -> list[dict]:
    """Clean role/content pairs to replay as `history` to bible_query()."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages"
            " WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]


def append_turn(
    conv_id: str,
    user_text: str,
    assistant_text: str,
    tool_log: str | None,
) -> tuple[int, str]:
    """Persist one user/assistant turn. Returns (assistant message id, title)."""
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at)"
            " VALUES (?, 'user', ?, ?)",
            (conv_id, user_text, now),
        )
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_log, created_at)"
            " VALUES (?, 'assistant', ?, ?, ?)",
            (conv_id, assistant_text, tool_log or None, now),
        )
        message_id = cur.lastrowid
        conn.execute(
            "UPDATE conversations SET updated_at = ?,"
            " title = CASE WHEN title = 'New chat' THEN ? ELSE title END"
            " WHERE id = ?",
            (now, user_text[:30], conv_id),
        )
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        # row is None if the conversation was deleted mid-query
        return message_id, (row["title"] if row else user_text[:30])


# ── usage ─────────────────────────────────────────────────────────────────────

def log_usage(
    user_id: str,
    conversation_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    cost_usd: float,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage_log (user_id, conversation_id, model,"
            " input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, cost_usd, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, conversation_id, model, input_tokens, output_tokens,
             cache_read_tokens, cache_write_tokens, cost_usd, _now()),
        )


_USAGE_SUMS = (
    "COUNT(*) AS queries,"
    " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
    " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
    " COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,"
    " COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,"
    " COALESCE(SUM(cost_usd), 0) AS cost_usd"
)


def get_usage(user_id: str, since: str | None = None) -> dict:
    """Aggregate totals for one user; `since` is an inclusive 'YYYY-MM-DD
    HH:MM:SS' lower bound (created_at is stored in that format, so plain
    string comparison is chronological)."""
    sql = f"SELECT {_USAGE_SUMS} FROM usage_log WHERE user_id = ?"
    params: list = [user_id]
    if since:
        sql += " AND created_at >= ?"
        params.append(since)
    with _connect() as conn:
        return dict(conn.execute(sql, params).fetchone())


def get_total_usage(since: str | None = None) -> dict:
    sql = f"SELECT {_USAGE_SUMS} FROM usage_log"
    params: list = []
    if since:
        sql += " WHERE created_at >= ?"
        params.append(since)
    with _connect() as conn:
        return dict(conn.execute(sql, params).fetchone())


def get_monthly_usage(user_id: str | None = None) -> list[dict]:
    """Per-month rollup (newest first) — for future usage charts.
    Pass user_id for one user, None for site-wide."""
    where = "WHERE user_id = ?" if user_id else ""
    params = (user_id,) if user_id else ()
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT strftime('%Y-%m', created_at) AS month, {_USAGE_SUMS}"
            f" FROM usage_log {where} GROUP BY month ORDER BY month DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


# ── feedback ──────────────────────────────────────────────────────────────────

def add_feedback(
    user_id: str,
    message_id: int,
    action: str,
    comment: str | None = None,
) -> bool:
    """Log a feedback event. Returns False if the message isn't the user's."""
    with _connect() as conn:
        owned = conn.execute(
            "SELECT 1 FROM messages m"
            " JOIN conversations c ON c.id = m.conversation_id"
            " WHERE m.id = ? AND c.user_id = ?",
            (message_id, user_id),
        ).fetchone()
        if owned is None:
            return False
        conn.execute(
            "INSERT INTO feedback (message_id, user_id, action, comment, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (message_id, user_id, action, comment, _now()),
        )
        return True
