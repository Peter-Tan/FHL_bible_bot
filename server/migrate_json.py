from __future__ import annotations

"""One-time import of the Gradio-era logs/user_<id>.json files into SQLite.

Run:  .venv/bin/python -m server.migrate_json   (from the repo root)

- Reuses the old 8-char user ids so existing browser cookies keep working
  (the session middleware falls back to the legacy `fhl_session_id` cookie).
- Idempotent: a user id already present in the DB is skipped entirely.
- The JSON files are left untouched as a backup.
"""

import json
import re
import uuid
from pathlib import Path

from . import db

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

# Old display format: "**🔧 Tool calls** (N calls)\n```\n<lines>\n```\n\n---\n\n<answer>"
_TOOL_BLOCK_RE = re.compile(
    r"^\*\*🔧 Tool calls\*\*[^\n]*\n```\n(?P<log>.*?)\n```\n\n---\n\n",
    re.DOTALL,
)


def _split_display(display: str) -> str | None:
    """Extract the tool-call log from an old display-format assistant message."""
    m = _TOOL_BLOCK_RE.match(display)
    return m.group("log") if m else None


def migrate() -> None:
    db.init_db()
    files = sorted(LOGS_DIR.glob("user_*.json"))
    imported = skipped = 0

    for path in files:
        user_id = path.stem[len("user_"):]
        if db.user_exists(user_id):
            skipped += 1
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"!! {path.name}: unreadable, skipped ({exc})")
            continue

        db.create_user(user_id)
        for session in data.get("sessions", []):
            api_history = session.get("api_history", [])
            display_msgs = session.get("messages", [])
            if not api_history:
                continue  # empty "New chat" sessions are not worth importing

            created = f"{session.get('created', '1970-01-01 00:00')}:00"
            conv_id = str(uuid.uuid4())
            with db._connect() as conn:
                conn.execute(
                    "INSERT INTO conversations"
                    " (id, user_id, title, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (conv_id, user_id,
                     session.get("title", "New chat"), created, created),
                )
                for i, msg in enumerate(api_history):
                    tool_log = None
                    if msg.get("role") == "assistant" and i < len(display_msgs):
                        tool_log = _split_display(display_msgs[i].get("content", ""))
                    conn.execute(
                        "INSERT INTO messages"
                        " (conversation_id, role, content, tool_log, created_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (conv_id, msg.get("role", "user"),
                         msg.get("content", ""), tool_log, created),
                    )
        imported += 1
        print(f"ok {path.name}")

    print(f"\nDone: {imported} user file(s) imported, {skipped} already in DB.")


if __name__ == "__main__":
    migrate()
