"""Current-user identity and per-user conversations (HA Ingress scoped)."""

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from core.identity import ensure_from_request, ensure_user, list_profiles
from core.config import BUILD_ID
from database import (
    create_conversation_session,
    delete_conversation_session,
    clear_conversation,
    get_conversation_sessions,
    get_session_messages,
)
from services import chat_content as cc
from services import chat_files as cf
from services import chat_media as cm

MAX_UPLOAD_BYTES = 4 * 1024 * 1024


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
    from services import session_chat as sc

    session_id = str(request.query_params.get("session_id") or "").strip()
    chat = sc.effective_chat_info(cfg, session_id or None, user_id=username)
    from services import atmosphere as atm

    from services import voice as vc

    dynamic = cfg.get("dynamic_greetings") is not False
    greeting_pool = []
    if dynamic:
        try:
            from services import greeting_pool as gp
            greeting_pool = gp.public_items(80)
            # Lazy refresh in background — don't block /api/me
            if gp.needs_refresh(cfg):
                import asyncio
                asyncio.create_task(gp.ensure_fresh())
        except Exception:
            greeting_pool = []
    return {
        "user": _public_profile(match),
        "language": cfg.get("language") or "en",
        "dynamic_greetings": dynamic,
        "greeting_pool": greeting_pool,
        "build": BUILD_ID,
        "voice": vc.public_status(cfg),
        "atmosphere": await atm.snapshot() if dynamic else {},
        "chat": chat,
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


@router.put("/api/conversations/{session_id}/provider")
async def set_session_provider(request: Request, session_id: str):
    """Set provider/model for this chat only — does not change Settings defaults."""
    from core.config import load_config
    from services import session_chat as sc

    user_id = _current_username(request)
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse(status_code=400, content={"error": "session_id required"})
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    auto = body.get("auto")
    provider_id = body.get("provider_id")
    model = body.get("model")

    if auto is True:
        override = sc.set_override(sid, auto=True, user_id=user_id)
    else:
        cfg = load_config()
        pool = [p for p in (cfg.get("providers") or []) if isinstance(p, dict)]
        pid = None if provider_id is None else str(provider_id).strip()
        mid = None if model is None else str(model).strip()
        if pid:
            match = next((p for p in pool if p.get("id") == pid), None)
            if match is None:
                return JSONResponse(status_code=404, content={"error": "Provider not found"})
            # Switching provider without an explicit model uses that provider's Settings model.
            if mid is None:
                mid = str(match.get("model") or "").strip()
        override = sc.set_override(
            sid,
            provider_id=pid,
            model=mid,
            auto=False,
            user_id=user_id,
        )

    cfg = load_config()
    chat = sc.effective_chat_info(cfg, sid, user_id=user_id)
    return {"status": "ok", "override": override, "chat": chat}


@router.delete("/api/conversations/{session_id}/toolkits")
async def clear_session_toolkits(request: Request, session_id: str):
    """Clear sticky Dynamic tool packs for this conversation."""
    from core.config import load_config
    from services import session_chat as sc
    from services import toolkits as tk

    user_id = _current_username(request)
    sid = str(session_id or "").strip()
    if not sid:
        return JSONResponse(status_code=400, content={"error": "session_id required"})
    tk.clear_sticky(sid, user_id=user_id)
    cfg = load_config()
    chat = sc.effective_chat_info(cfg, sid, user_id=user_id)
    return {"status": "ok", "chat": chat}


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
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
        ".html": "text/html",
        ".htm": "text/html",
        ".rtf": "application/rtf",
        ".log": "text/plain",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".weba": "audio/webm",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".m4v": "video/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=mime, filename=path.name)


def _attachment_payload(user_id: str, att: dict, fallback_name: str = "") -> dict:
    public_url = cm.attachment_public_url(att["id"])
    kind = str(att.get("kind") or "image")
    if kind == "audio":
        return {
            "id": att["id"],
            "mime": att.get("mime") or "audio/mpeg",
            "name": att.get("name") or fallback_name or "audio",
            "kind": "audio",
            "url": public_url,
        }
    if kind == "video":
        return {
            "id": att["id"],
            "mime": att.get("mime") or "video/mp4",
            "name": att.get("name") or fallback_name or "video",
            "kind": "video",
            "url": public_url,
        }
    if kind == "document":
        text = cm.read_extracted_text(user_id, att) or ""
        return {
            "id": att["id"],
            "mime": att.get("mime") or "text/plain",
            "name": att.get("name") or fallback_name or "document",
            "kind": "document",
            "url": public_url,
            "text": text,
            "chars": len(text),
        }
    return {
        "id": att["id"],
        "mime": att.get("mime") or "image/jpeg",
        "name": att.get("name") or fallback_name or "image",
        "kind": "image",
        "url": public_url,
        "dataUrl": cm.attachment_data_url(user_id, att),
    }


def _save_error(exc: ValueError) -> JSONResponse:
    msg = str(exc)
    code = 413 if "too large" in msg.lower() else 400
    return JSONResponse(status_code=code, content={"error": msg})


@router.post("/api/chat/upload")
async def chat_upload(request: Request, file: UploadFile = File(...)):
    """Upload a chat image or document via multipart form."""
    user_id = _current_username(request)
    raw = await file.read()
    if not raw:
        return JSONResponse(status_code=400, content={"error": "Empty file"})
    if len(raw) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": "File too large"})
    try:
        att = cm.save_uploaded_file(
            user_id,
            raw,
            filename=file.filename or "",
            content_type=file.content_type or "",
        )
    except ValueError as exc:
        return _save_error(exc)
    return _attachment_payload(user_id, att, file.filename or "")


@router.get("/api/chat/files")
async def chat_files(request: Request, path: str = "", kind: str = ""):
    """Browse /share and /media (Companion app has no working native file picker)."""
    _current_username(request)
    try:
        return cf.list_dir(path, kind=kind)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@router.post("/api/chat/files/attach")
async def chat_files_attach(request: Request, data: dict):
    """Attach a file that already lives on /share or /media — no upload dialog."""
    user_id = _current_username(request)
    raw_path = str((data or {}).get("path") or "").strip()
    try:
        raw, name = cf.read_file(raw_path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    try:
        att = cm.save_uploaded_file(user_id, raw, filename=name)
    except ValueError as exc:
        return _save_error(exc)
    return _attachment_payload(user_id, att, name)


@router.post("/api/chat/voice/transcribe")
async def chat_voice_transcribe(
    request: Request,
    file: UploadFile = File(...),
    sample_rate: int = 16000,
):
    """Recorded WAV (16 kHz mono) → transcript, for the mic button."""
    from services import google_voice as gv
    from services import voice as vc

    _current_username(request)
    raw = await file.read()
    if not raw:
        return JSONResponse(status_code=400, content={"error": "Empty recording"})
    if len(raw) > gv.MAX_STT_BYTES:
        return JSONResponse(status_code=413, content={"error": "Recording too long"})
    try:
        text = await vc.transcribe(raw, sample_rate=sample_rate)
    except gv.VoiceError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
    return {"text": text}


@router.post("/api/chat/voice/speak")
async def chat_voice_speak(request: Request, data: dict):
    """Text → spoken MP3 attachment the chat can play."""
    from services import google_voice as gv
    from services import voice as vc

    user_id = _current_username(request)
    text = str((data or {}).get("text") or "")
    try:
        return await vc.speak(user_id, text)
    except gv.VoiceError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
    except ValueError as exc:
        return _save_error(exc)


@router.delete("/api/conversations/{session_id}")
async def delete_mine(request: Request, session_id: str):
    from services import session_chat as sc
    from services import toolkits as tk

    user_id = _current_username(request)
    delete_conversation_session(user_id, session_id)
    sc.clear(session_id)
    tk.clear_sticky(session_id)
    return {"status": "ok", "user_id": user_id, "session_id": session_id}


@router.delete("/api/conversations")
async def delete_all_mine(request: Request):
    """Delete all conversation sessions for the current user."""
    user_id = _current_username(request)
    clear_conversation(user_id)
    return {"status": "ok", "user_id": user_id}
