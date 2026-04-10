import time
import uuid
import socket
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import load_config, save_config
from core.config import VERSION
from database import get_db, get_all_users, get_conversation_sessions, get_session_messages, delete_conversation_session
from services import lmstudio, searxng

router = APIRouter(prefix="/api/settings", tags=["settings"])

_start_time = time.time()


def _get_local_ip() -> str:
    """Get the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SettingsUpdate(BaseModel):
    lmstudio: dict | None = None
    searxng: dict | None = None
    memory: dict | None = None
    performance: dict | None = None
    system_prompt: str | None = None
    knowledge_cutoff: str | None = None
    language: str | None = None


@router.get("/")
async def get_settings():
    return load_config()


@router.put("/")
async def update_settings(data: SettingsUpdate):
    cfg = load_config()
    if data.lmstudio is not None:
        cfg["lmstudio"].update(data.lmstudio)
    if data.searxng is not None:
        cfg["searxng"].update(data.searxng)
    if data.memory is not None:
        cfg["memory"].update(data.memory)
    if data.performance is not None:
        cfg.setdefault("performance", {}).update(data.performance)
    if data.system_prompt is not None:
        cfg["system_prompt"] = data.system_prompt
    if data.knowledge_cutoff is not None:
        cfg["knowledge_cutoff"] = data.knowledge_cutoff
    if data.language is not None:
        cfg["language"] = data.language
    save_config(cfg)
    return {"status": "ok", "config": cfg}


@router.put("/users/default")
async def set_default_user(data: dict):
    username = data.get("username", "").strip()
    cfg = load_config()
    cfg.setdefault("users", {})["default_user"] = username
    save_config(cfg)
    return {"status": "ok", "default_user": username}


@router.post("/users")
async def add_user(data: dict):
    username = data.get("username", "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    cfg = load_config()
    users = cfg.setdefault("users", {"default_user": "", "api_keys": {}})
    api_keys = users.setdefault("api_keys", {})
    for key, name in api_keys.items():
        if name == username:
            raise HTTPException(status_code=409, detail="User already exists")
    new_key = f"hab_{uuid.uuid4().hex}"
    api_keys[new_key] = username
    save_config(cfg)
    return {"username": username, "api_key": new_key}


@router.delete("/users/{username}")
async def delete_user(username: str):
    cfg = load_config()
    api_keys = cfg.get("users", {}).get("api_keys", {})
    to_remove = [k for k, v in api_keys.items() if v == username]
    for k in to_remove:
        del api_keys[k]
    if to_remove:
        save_config(cfg)
    return {"status": "ok", "removed": len(to_remove)}


@router.get("/health")
async def health():
    lm_ok = await lmstudio.health_check()
    sx_ok = await searxng.health_check()
    return {
        "lmstudio": "connected" if lm_ok else "unreachable",
        "searxng": "connected" if sx_ok else "unreachable",
    }


@router.get("/info")
async def system_info():
    """System info for the Info dashboard tab."""
    cfg = load_config()
    uptime = time.time() - _start_time

    # DB stats
    with get_db() as conn:
        total_memories = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE active = 1"
        ).fetchone()["c"]
        total_conversations = conn.execute(
            "SELECT COUNT(*) as c FROM conversations"
        ).fetchone()["c"]
        total_users = len(get_all_users())
        recent_actions = conn.execute(
            "SELECT COUNT(*) as c FROM memory_log WHERE created_at > ?",
            (time.time() - 86400,),
        ).fetchone()["c"]

    lm_ok = await lmstudio.health_check()
    sx_ok = await searxng.health_check()

    return {
        "version": VERSION,
        "uptime_seconds": round(uptime),
        "api_key": cfg.get("api_key", ""),
        "local_ip": _get_local_ip(),
        "port": 8899,
        "services": {
            "lmstudio": {
                "status": "connected" if lm_ok else "unreachable",
                "url": cfg["lmstudio"]["base_url"],
                "model": cfg["lmstudio"]["model"],
            },
            "searxng": {
                "status": "connected" if sx_ok else "unreachable",
                "enabled": cfg["searxng"]["enabled"],
                "url": cfg["searxng"]["base_url"],
            },
            "memory": {
                "enabled": cfg["memory"]["enabled"],
                "auto_extract": cfg["memory"]["auto_extract"],
            },
        },
        "stats": {
            "total_memories": total_memories,
            "total_conversations": total_conversations,
            "total_users": total_users,
            "actions_last_24h": recent_actions,
        },
        "endpoints": [
            {"method": "POST", "path": "/v1/chat/completions", "description": "Chat Completions (OpenAI-compatible)"},
            {"method": "GET", "path": "/v1/models", "description": "List Models (OpenAI)"},
            {"method": "GET", "path": "/api/settings/", "description": "Get Settings"},
            {"method": "PUT", "path": "/api/settings/", "description": "Update Settings"},
            {"method": "GET", "path": "/api/settings/health", "description": "Health Check"},
            {"method": "GET", "path": "/api/settings/info", "description": "System Info"},
            {"method": "POST", "path": "/api/settings/users", "description": "Add User + Generate API Key"},
            {"method": "DELETE", "path": "/api/settings/users/{username}", "description": "Delete User"},
            {"method": "PUT", "path": "/api/settings/users/default", "description": "Set Default User"},
            {"method": "GET", "path": "/api/settings/conversations/{user_id}", "description": "List Conversation Sessions"},
            {"method": "GET", "path": "/api/settings/conversations/{user_id}/{session_id}", "description": "Get Session Messages"},
            {"method": "GET", "path": "/api/settings/backup", "description": "Download Database Backup"},
            {"method": "POST", "path": "/api/settings/restore", "description": "Restore Database from Backup"},
            {"method": "GET", "path": "/api/memory/users", "description": "List Users"},
            {"method": "GET", "path": "/api/memory/stats/{user_id}", "description": "Memory Stats"},
            {"method": "GET", "path": "/api/memory/{user_id}", "description": "List Memories"},
            {"method": "POST", "path": "/api/memory/", "description": "Add Memory"},
            {"method": "PUT", "path": "/api/memory/{memory_id}", "description": "Update Memory"},
            {"method": "DELETE", "path": "/api/memory/{memory_id}", "description": "Delete Memory"},
            {"method": "DELETE", "path": "/api/memory/user/{user_id}", "description": "Clear User Memories"},
            {"method": "POST", "path": "/api/memory/consolidate/{user_id}", "description": "Consolidate Memories"},
        ],
    }


# ══════════════════════════════════════════════════
# Conversation viewer endpoints
# ══════════════════════════════════════════════════

@router.post("/restart")
async def restart_server():
    """Restart the HASSAI Bridge server by triggering uvicorn reload."""
    from pathlib import Path
    import time
    trigger = Path(__file__).parent.parent / ".restart_trigger"
    trigger.write_text(str(time.time()))
    return {"status": "ok", "message": "Server is restarting..."}


@router.get("/conversations/{user_id}")
async def list_conversations(user_id: str, limit: int = 20):
    """List conversation sessions for a user."""
    sessions = get_conversation_sessions(user_id, limit)
    return {"user_id": user_id, "sessions": sessions}


@router.get("/conversations/{user_id}/{session_id}")
async def get_session(user_id: str, session_id: str, limit: int = 100):
    """Get all messages in a conversation session."""
    messages = get_session_messages(user_id, session_id, limit)
    return {"user_id": user_id, "session_id": session_id, "messages": messages}


@router.delete("/conversations/{user_id}/{session_id}")
async def delete_session(user_id: str, session_id: str):
    """Delete a conversation session."""
    delete_conversation_session(user_id, session_id)
    return {"status": "ok"}


# ══════════════════════════════════════════════════
# Database backup / restore
# ══════════════════════════════════════════════════

@router.get("/backup")
async def backup_database():
    """Download the SQLite database as a file."""
    from fastapi.responses import FileResponse as FR
    from database import DB_PATH
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Database not found")
    return FR(
        path=str(DB_PATH),
        filename="hassai_backup.db",
        media_type="application/octet-stream",
    )


@router.post("/restore")
async def restore_database(file: bytes = None):
    """Restore database from uploaded file."""
    import shutil
    from fastapi import UploadFile
    from database import DB_PATH, init_db
    raise HTTPException(status_code=400, detail="Use the upload endpoint")


from fastapi import UploadFile, File as FastAPIFile


@router.post("/restore/upload")
async def restore_database_upload(file: UploadFile = FastAPIFile(...)):
    """Restore database from uploaded .db file."""
    import shutil
    from database import DB_PATH

    if not file.filename or not file.filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="Only .db files are accepted")

    # Read uploaded file (limit to 100MB)
    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")

    # Validate it's a valid SQLite file
    if not contents[:16].startswith(b"SQLite format 3"):
        raise HTTPException(status_code=400, detail="Invalid SQLite database file")

    # Backup current DB before replacing
    backup_path = DB_PATH.with_suffix(".db.bak")
    if DB_PATH.exists():
        shutil.copy2(str(DB_PATH), str(backup_path))

    # Write the new database
    with open(str(DB_PATH), "wb") as f:
        f.write(contents)

    return {"status": "ok", "message": "Database restored successfully", "size": len(contents)}