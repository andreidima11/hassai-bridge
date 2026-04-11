import time
import uuid
import socket
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from config import load_config, save_config
from core.config import VERSION
from database import get_db, get_all_users, get_conversation_sessions, get_session_messages, delete_conversation_session, get_usage_stats
from services import providers, searxng
from services.providers import get_active_provider, PROVIDER_PRESETS


def _require_admin_key(request: Request):
    """Import-free admin auth — delegates to main._require_admin_key at runtime."""
    from main import _require_admin_key as _auth
    return _auth(request)


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(_require_admin_key)],
)

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
    active_provider: str | None = None
    providers: list | None = None


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
    if data.active_provider is not None:
        cfg["active_provider"] = data.active_provider
    if data.providers is not None:
        cfg["providers"] = data.providers
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


# ══════════════════════════════════════════════════
# Provider management endpoints
# ══════════════════════════════════════════════════

@router.get("/providers/presets")
async def get_provider_presets():
    """Return available provider type presets (base URLs, etc.)."""
    return PROVIDER_PRESETS


@router.get("/providers")
async def list_providers():
    """List all configured providers."""
    cfg = load_config()
    return {
        "providers": cfg.get("providers", []),
        "active_provider": cfg.get("active_provider", ""),
    }


@router.post("/providers")
async def add_provider(data: dict):
    """Add a new provider."""
    ptype = data.get("type", "local")
    name = data.get("name", "").strip()
    base_url = data.get("base_url", "").strip()
    api_key = data.get("api_key", "").strip()
    model = data.get("model", "default").strip()
    timeout = data.get("timeout", 120)
    max_tokens = data.get("max_tokens", 2048)
    temperature = data.get("temperature", 0.7)
    system_prompt = data.get("system_prompt", "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    if not base_url:
        preset = PROVIDER_PRESETS.get(ptype, {})
        base_url = preset.get("base_url", "http://localhost:1234")

    # Generate a stable ID from type + name
    pid = f"{ptype}_{name.lower().replace(' ', '_').replace('-', '_')}"
    # Ensure unique
    cfg = load_config()
    existing_ids = {p["id"] for p in cfg.get("providers", [])}
    if pid in existing_ids:
        suffix = 2
        while f"{pid}_{suffix}" in existing_ids:
            suffix += 1
        pid = f"{pid}_{suffix}"

    provider = {
        "id": pid,
        "name": name,
        "type": ptype,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout": timeout,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system_prompt": system_prompt,
    }
    cfg.setdefault("providers", []).append(provider)
    # Auto-activate if first provider
    if len(cfg["providers"]) == 1:
        cfg["active_provider"] = pid
    save_config(cfg)
    return {"status": "ok", "provider": provider}


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, data: dict):
    """Update an existing provider."""
    cfg = load_config()
    for p in cfg.get("providers", []):
        if p["id"] == provider_id:
            for key in ("name", "type", "base_url", "api_key", "model", "timeout", "max_tokens", "temperature", "system_prompt"):
                if key in data:
                    p[key] = data[key]
            save_config(cfg)
            return {"status": "ok", "provider": p}
    raise HTTPException(status_code=404, detail="Provider not found")


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """Delete a provider."""
    cfg = load_config()
    plist = cfg.get("providers", [])
    cfg["providers"] = [p for p in plist if p["id"] != provider_id]
    if cfg.get("active_provider") == provider_id:
        cfg["active_provider"] = cfg["providers"][0]["id"] if cfg["providers"] else ""
    save_config(cfg)
    return {"status": "ok"}


@router.put("/providers/{provider_id}/activate")
async def activate_provider(provider_id: str):
    """Set a provider as active."""
    cfg = load_config()
    for p in cfg.get("providers", []):
        if p["id"] == provider_id:
            cfg["active_provider"] = provider_id
            save_config(cfg)
            return {"status": "ok", "active_provider": provider_id}
    raise HTTPException(status_code=404, detail="Provider not found")


@router.get("/providers/{provider_id}/models")
async def get_provider_models(provider_id: str):
    """List models available on a specific provider."""
    cfg = load_config()
    for p in cfg.get("providers", []):
        if p["id"] == provider_id:
            try:
                models = await providers.list_models(p)
                return {"models": models}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Could not reach provider: {e}")
    raise HTTPException(status_code=404, detail="Provider not found")


@router.get("/providers/{provider_id}/health")
async def check_provider_health(provider_id: str):
    """Health check for a specific provider."""
    cfg = load_config()
    for p in cfg.get("providers", []):
        if p["id"] == provider_id:
            ok = await providers.health_check(p)
            return {"status": "connected" if ok else "unreachable", "provider": p["name"]}
    raise HTTPException(status_code=404, detail="Provider not found")


@router.get("/health")
async def health():
    active = get_active_provider()
    provider_ok = await providers.health_check(active)
    sx_ok = await searxng.health_check()
    return {
        "provider": "connected" if provider_ok else "unreachable",
        "provider_name": active.get("name", "?"),
        "provider_type": active.get("type", "?"),
        # Keep lmstudio key for backward compatibility
        "lmstudio": "connected" if provider_ok else "unreachable",
        "searxng": "connected" if sx_ok else "unreachable",
    }


def _mask_key(key: str) -> str:
    """Mask an API key for safe display: show first 8 + last 4 chars."""
    if not key or len(key) <= 12:
        return "***" if key else ""
    return key[:8] + "..." + key[-4:]


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

    lm_ok = await providers.health_check()
    sx_ok = await searxng.health_check()
    active = get_active_provider()

    # Mask API keys in response (#10)
    safe_providers = []
    for p in cfg.get("providers", []):
        sp = dict(p)
        if sp.get("api_key"):
            sp["api_key"] = _mask_key(sp["api_key"])
        safe_providers.append(sp)

    return {
        "version": VERSION,
        "uptime_seconds": round(uptime),
        "api_key": _mask_key(cfg.get("api_key", "")),
        "local_ip": _get_local_ip(),
        "port": 8899,
        "active_provider": cfg.get("active_provider", ""),
        "providers": safe_providers,
        "services": {
            "lmstudio": {
                "status": "connected" if lm_ok else "unreachable",
                "url": active.get("base_url", ""),
                "model": active.get("model", "default"),
            },
            "provider": {
                "status": "connected" if lm_ok else "unreachable",
                "id": active.get("id", ""),
                "name": active.get("name", "?"),
                "type": active.get("type", "local"),
                "url": active.get("base_url", ""),
                "model": active.get("model", "default"),
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
            {"method": "GET", "path": "/api/settings/stats", "description": "Usage Statistics"},
            {"method": "POST", "path": "/api/settings/restart", "description": "Restart Server"},
            {"method": "POST", "path": "/api/settings/users", "description": "Add User + Generate API Key"},
            {"method": "DELETE", "path": "/api/settings/users/{username}", "description": "Delete User"},
            {"method": "PUT", "path": "/api/settings/users/default", "description": "Set Default User"},
            {"method": "GET", "path": "/api/settings/providers", "description": "List Providers"},
            {"method": "POST", "path": "/api/settings/providers", "description": "Add Provider"},
            {"method": "PUT", "path": "/api/settings/providers/{id}", "description": "Update Provider"},
            {"method": "DELETE", "path": "/api/settings/providers/{id}", "description": "Delete Provider"},
            {"method": "PUT", "path": "/api/settings/providers/{id}/activate", "description": "Activate Provider"},
            {"method": "GET", "path": "/api/settings/providers/{id}/models", "description": "List Provider Models"},
            {"method": "GET", "path": "/api/settings/providers/{id}/health", "description": "Provider Health Check"},
            {"method": "GET", "path": "/api/settings/providers/presets", "description": "Provider Presets"},
            {"method": "GET", "path": "/api/settings/conversations/{user_id}", "description": "List Conversation Sessions"},
            {"method": "GET", "path": "/api/settings/conversations/{user_id}/{session_id}", "description": "Get Session Messages"},
            {"method": "DELETE", "path": "/api/settings/conversations/{user_id}/{session_id}", "description": "Delete Session"},
            {"method": "GET", "path": "/api/settings/backup", "description": "Download Database Backup"},
            {"method": "POST", "path": "/api/settings/restore", "description": "Restore Database (path)"},
            {"method": "POST", "path": "/api/settings/restore/upload", "description": "Restore Database (upload)"},
            {"method": "GET", "path": "/api/memory/categories", "description": "Memory Categories"},
            {"method": "GET", "path": "/api/memory/users", "description": "List Users"},
            {"method": "GET", "path": "/api/memory/stats/{user_id}", "description": "Memory Stats"},
            {"method": "GET", "path": "/api/memory/{user_id}", "description": "List Memories"},
            {"method": "POST", "path": "/api/memory/", "description": "Add Memory"},
            {"method": "PUT", "path": "/api/memory/{memory_id}", "description": "Update Memory"},
            {"method": "DELETE", "path": "/api/memory/{memory_id}", "description": "Delete Memory"},
            {"method": "DELETE", "path": "/api/memory/user/{user_id}", "description": "Clear User Memories"},
            {"method": "POST", "path": "/api/memory/consolidate/{user_id}", "description": "Consolidate Memories"},
            {"method": "GET", "path": "/api/memory/graph/{user_id}/stats", "description": "Knowledge Graph Stats"},
            {"method": "GET", "path": "/api/memory/graph/{user_id}/entities", "description": "List Graph Entities"},
            {"method": "GET", "path": "/api/memory/graph/{user_id}/entity/{name}", "description": "Entity Detail"},
            {"method": "POST", "path": "/api/memory/graph/{user_id}/entity", "description": "Add Graph Entity"},
            {"method": "DELETE", "path": "/api/memory/graph/{user_id}/entity/{name}", "description": "Delete Graph Entity"},
            {"method": "GET", "path": "/api/memory/graph/{user_id}/relations", "description": "Query Relations"},
            {"method": "POST", "path": "/api/memory/graph/{user_id}/relation", "description": "Add Relation"},
            {"method": "POST", "path": "/api/memory/graph/{user_id}/invalidate", "description": "Invalidate Relation"},
            {"method": "GET", "path": "/api/memory/graph/{user_id}/timeline", "description": "Knowledge Timeline"},
            {"method": "GET", "path": "/api/memory/graph/{user_id}/context", "description": "Graph Context"},
            {"method": "GET", "path": "/api/logs", "description": "Server Logs"},
        ],
    }


# ══════════════════════════════════════════════════
# Usage statistics endpoint
# ══════════════════════════════════════════════════

@router.get("/stats")
async def get_stats(days: int = 30):
    """Get usage statistics for the dashboard."""
    if days < 1:
        days = 1
    elif days > 365:
        days = 365
    return get_usage_stats(days)


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
    """Deprecated — use /restore/upload."""
    raise HTTPException(status_code=410, detail="Deprecated. Use POST /api/settings/restore/upload")


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