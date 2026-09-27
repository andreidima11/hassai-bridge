"""HTTP API for durable chat jobs (feed / active session)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.config import load_config
from services.chat_jobs import manager, store

router = APIRouter(tags=["chat-jobs"])


def _require_admin_key(request: Request):
    from main import _require_admin_key as _auth

    return _auth(request)


def _current_username(request: Request) -> str:
    from core.identity import ensure_from_request
    from routers.chat import _extract_user_id

    ensure_from_request(request)
    return _extract_user_id(request, {})


@router.get("/api/chat-jobs", dependencies=[Depends(_require_admin_key)])
async def list_chat_jobs(request: Request, session_id: str = "", limit: int = 20):
    user_id = _current_username(request)
    sid = str(session_id or "").strip() or None
    jobs = store.list_jobs(user_id, session_id=sid, limit=limit)
    return {"jobs": [manager.public_job(j) for j in jobs]}


@router.get("/api/chat-jobs/active", dependencies=[Depends(_require_admin_key)])
async def active_chat_job(request: Request, session_id: str = ""):
    user_id = _current_username(request)
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    job = store.active_job_for_session(user_id, sid)
    return {"ok": True, "job": manager.public_job(job)}


@router.get("/api/chat-jobs/feed", dependencies=[Depends(_require_admin_key)])
async def chat_jobs_feed(request: Request, session_id: str = "", after: int = 0):
    user_id = _current_username(request)
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    cfg = load_config()
    out = manager.feed(sid, after_seq=int(after or 0), owner_id=user_id)
    out["poll_seconds"] = manager._cj_cfg(cfg)["feed_poll_seconds"]
    return out
