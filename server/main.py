from __future__ import annotations

"""FastAPI app factory.

Run:  .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 7860
(from the repo root; the venv's Python is 3.9, and `uv run` would resolve the
unrelated gemma4-nlp pyproject, so invoke uvicorn via the venv directly.)
"""

import os
import sys
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi import FastAPI  # noqa: E402

from . import chat, db, sessions  # noqa: E402

db.init_db()

app = FastAPI(title="FHL Bible Tool API", docs_url=None, redoc_url=None)
app.middleware("http")(sessions.session_middleware)
# Public path is tech.fhl.net/bible_bot/ — nginx strips the prefix and
# proxies /api/*. The /bible_bot prefix routes make the same API reachable
# without nginx (single-process serving / local testing).
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(sessions.router, prefix="/bible_bot")
app.include_router(chat.router, prefix="/bible_bot")

# Serve the built SPA from FastAPI itself (nginx can also serve web/dist
# directly in prod; this makes single-process serving possible at /bible_bot/).
_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    app.mount(
        "/bible_bot",
        StaticFiles(directory=str(_dist), html=True),
        name="spa",
    )
