"""HTTP API for background tasks (list / cancel / feed)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.config import load_config
from services.background_tasks import manager

router = APIRouter(tags=["background-tasks"])


def _require_admin_key(request: Request):
    from main import _require_admin_key as _auth

    return _auth(request)


def _current_username(request: Request) -> str:
    from core.identity import ensure_from_request
    from routers.chat import _extract_user_id

    ensure_from_request(request)
    return _extract_user_id(request, {})


@router.get("/api/background-tasks", dependencies=[Depends(_require_admin_key)])
async def list_background_tasks(request: Request, session_id: str = "", limit: int = 20):
    user_id = _current_username(request)
    sid = str(session_id or "").strip() or None
    return manager.list_tasks(user_id, limit=limit, session_id=sid)


@router.post("/api/background-tasks/{task_id}/cancel", dependencies=[Depends(_require_admin_key)])
async def cancel_background_task(request: Request, task_id: str):
    user_id = _current_username(request)
    tid = str(task_id or "").strip()
    if not tid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "task_id required"})
    out = manager.cancel_task(tid, owner_id=user_id)
    if not out.get("ok"):
        return JSONResponse(status_code=404, content=out)
    return out


@router.get("/api/background-tasks/feed", dependencies=[Depends(_require_admin_key)])
async def background_tasks_feed(request: Request, session_id: str = "", after: int = 0):
    user_id = _current_username(request)
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    cfg = load_config()
    poll = int(((cfg.get("background_tasks") or {}).get("feed_poll_seconds") or 3))
    out = manager.feed(sid, after_seq=int(after or 0), owner_id=user_id)
    out["poll_seconds"] = max(1, min(poll, 30))
    return out
