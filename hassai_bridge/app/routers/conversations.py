"""Current-user identity and per-user conversations (HA Ingress scoped)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from core.identity import ensure_from_request, ensure_user, list_profiles
from core.config import BUILD_ID
from database import (
    create_conversation_session,
    delete_conversation_session,
    get_conversation_sessions,
    get_session_messages,
)
from services import chat_content as cc
from services import chat_media as cm


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
    active = get_active_provider()
    from services.provider_capabilities import provider_chat_capabilities

    return {
        "user": _public_profile(match),
        "language": cfg.get("language") or "en",
        "build": BUILD_ID,
        "chat": {
            "provider_id": active.get("id", ""),
            "provider_type": active.get("type", ""),
            "provider_name": active.get("name", ""),
            "capabilities": provider_chat_capabilities(active),
        },
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
    for item in messages:
        attachments = item.get("attachments")
        if isinstance(attachments, list) and attachments:
            item["attachments"] = cc.public_attachments(attachments, session_id)
    return {"user_id": user_id, "session_id": session_id, "messages": messages}


@router.get("/api/chat/media/{attachment_id}")
async def chat_media(request: Request, attachment_id: str):
    user_id = _current_username(request)
    path = cm.resolve_attachment_path(user_id, attachment_id)
    if not path or not path.is_file():
        return JSONResponse(status_code=404, content={"error": "Not found"})
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=mime, filename=path.name)


@router.delete("/api/conversations/{session_id}")
async def delete_mine(request: Request, session_id: str):
    user_id = _current_username(request)
    delete_conversation_session(user_id, session_id)
    return {"status": "ok", "user_id": user_id, "session_id": session_id}
