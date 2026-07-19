from __future__ import annotations

"""Anonymous-cookie auth middleware + conversation CRUD endpoints."""

import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import db

COOKIE_NAME = "fhl_session"
LEGACY_COOKIE_NAME = "fhl_session_id"  # set by the old Gradio app.py
COOKIE_MAX_AGE = 180 * 24 * 3600  # 180 days

router = APIRouter(prefix="/api")


async def session_middleware(request: Request, call_next):
    """Ensure every /api request is bound to a user row; set cookie if new.

    Legacy path: if the old Gradio cookie holds an id that was imported by
    migrate_json.py, adopt it so existing users keep their history.
    """
    path = request.url.path
    if not (path.startswith("/api") or path.startswith("/bible_bot/api")):
        return await call_next(request)

    user_id = request.cookies.get(COOKIE_NAME)
    needs_cookie = False
    if not user_id or not db.user_exists(user_id):
        legacy_id = request.cookies.get(LEGACY_COOKIE_NAME)
        if legacy_id and db.user_exists(legacy_id):
            user_id = legacy_id
        else:
            user_id = secrets.token_urlsafe(32)
            db.create_user(user_id)
        needs_cookie = True

    request.state.user_id = user_id
    response = await call_next(request)
    if needs_cookie:
        response.set_cookie(
            COOKIE_NAME,
            user_id,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/usage")
async def get_usage(request: Request):
    """This-month + all-time token/cost totals for the cookie's user and
    site-wide. Per-query rows live in usage_log, so finer rollups (see
    db.get_monthly_usage) can back charts later."""
    now = datetime.now()
    month_start = now.strftime("%Y-%m-01 00:00:00")
    uid = request.state.user_id
    return {
        "month": now.strftime("%Y-%m"),
        "user": {
            "month": db.get_usage(uid, since=month_start),
            "all_time": db.get_usage(uid),
        },
        "total": {
            "month": db.get_total_usage(since=month_start),
            "all_time": db.get_total_usage(),
        },
    }


@router.get("/conversations")
async def list_conversations(request: Request):
    return db.list_conversations(request.state.user_id)


@router.post("/conversations")
async def create_conversation(request: Request):
    return db.create_conversation(request.state.user_id)


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, request: Request):
    conv = db.get_conversation(request.state.user_id, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: str, request: Request):
    if not db.delete_conversation(request.state.user_id, conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


class FeedbackRequest(BaseModel):
    action: str  # 'copy' | 'good' | 'bad' | 'comment'
    comment: Optional[str] = None


@router.post("/messages/{message_id}/feedback", status_code=204)
async def add_feedback(message_id: int, body: FeedbackRequest, request: Request):
    if body.action not in ("copy", "good", "bad", "comment"):
        raise HTTPException(status_code=400, detail="Invalid action")
    if body.action == "comment" and not (body.comment or "").strip():
        raise HTTPException(status_code=400, detail="Empty comment")
    ok = db.add_feedback(
        request.state.user_id, message_id, body.action,
        (body.comment or "").strip() or None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    return Response(status_code=204)
