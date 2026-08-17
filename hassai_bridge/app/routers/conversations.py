"""Current-user identity and per-user conversations (HA Ingress scoped)."""

from fastapi import APIRouter, Depends, Request

from core.identity import ensure_from_request, ensure_user, list_profiles
from core.config import BUILD_ID
from database import (
    create_conversation_session,
    delete_conversation_session,
    get_conversation_sessions,
    get_session_messages,
)


def _require_admin_key(request: Request):
    from main import _require_admin_key as _auth
    return _auth(request)


router = APIRouter(tags=["conversations"], dependencies=[Depends(_require_admin_key)])


def _current_username(request: Request) -> str:
    """Same identity rules as chat: API key, then HA Ingress, then default."""
    ensure_from_request(request)
    from routers.chat import _extract_user_id
    return _extract_user_id(request, {})


def _public_profile(profile: dict) -> dict:
    return {
        "username": profile.get("username") or "default",
        "ha_id": profile.get("ha_id") or "",
        "display_name": profile.get("display_name") or profile.get("username") or "default",
        "source": profile.get("source") or "webui",
    }


@router.get("/api/me")
async def me(request: Request):
    from core.config import load_config

    ensure_from_request(request)
    from routers.chat import _extract_user_id
    username = _extract_user_id(request, {})
    match = next((p for p in list_profiles() if p["username"] == username), None)
    if not match:
        try:
            match = ensure_user(username, source="webui")
        except ValueError:
            match = {
                "username": username or "default",
                "ha_id": "",
                "display_name": username or "default",
                "source": "webui",
            }
    cfg = load_config()
    return {
        "user": _public_profile(match),
        "language": cfg.get("language") or "en",
        "build": BUILD_ID,
    }


@router.get("/api/conversations")
async def list_mine(request: Request, limit: int = 50):
    user_id = _current_username(request)
    sessions = get_conversation_sessions(user_id, limit)
    return {"user_id": user_id, "sessions": sessions}


@router.post("/api/conversations")
async def new_mine(request: Request):
    user_id = _current_username(request)
    session_id = create_conversation_session()
    return {"user_id": user_id, "session_id": session_id}


@router.get("/api/conversations/{session_id}")
async def get_mine(request: Request, session_id: str, limit: int = 200):
    user_id = _current_username(request)
    messages = get_session_messages(user_id, session_id, limit)
    return {"user_id": user_id, "session_id": session_id, "messages": messages}


@router.delete("/api/conversations/{session_id}")
async def delete_mine(request: Request, session_id: str):
    user_id = _current_username(request)
    delete_conversation_session(user_id, session_id)
    return {"status": "ok", "user_id": user_id, "session_id": session_id}
