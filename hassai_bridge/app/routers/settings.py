import asyncio
import re
import time
import socket
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File as FastAPIFile, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from config import load_config, save_config
from core.config import VERSION, BUILD_ID
from database import get_db, get_all_users, get_conversation_sessions, get_session_messages, delete_conversation_session, bulk_delete_conversation_sessions, get_usage_stats, delete_user_data
from services import providers, searxng
from services.providers import get_active_provider, PROVIDER_PRESETS
from services import homeassistant as ha_api
from services import export_import as ei_export
from services.secondary_routing import normalize_use_for, use_for_labels

def _require_admin_key(request: Request):
    """Import-free admin auth — delegates to main._require_admin_key at runtime."""
    from main import _require_admin_key as _auth
    return _auth(request)


def _provider_id_slug(name: str) -> str:
    """Stable id fragment from a display name — alnum + underscore only."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "provider"


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
    frigate: dict | None = None
    memory: dict | None = None
    voice: dict | None = None
    performance: dict | None = None
    security: dict | None = None
    system_prompt: str | None = None
    ha_agent_prompt: str | None = None
    knowledge_cutoff: str | None = None
    language: str | None = None
    dynamic_greetings: bool | None = None
    greetings: dict | None = None
    ha_tools: dict | None = None
    bridge_tools: dict | None = None
    active_provider: str | None = None
    providers: list | None = None
    routing: dict | None = None
    pricing: dict | None = None


@router.get("/")
async def get_settings():
    return load_config()


@router.get("/ha-agent-prompt-default")
async def ha_agent_prompt_default():
    from services.entity_tools import DEFAULT_HA_AGENT_PROMPT
    return {"prompt": DEFAULT_HA_AGENT_PROMPT}


@router.get("/memory-extract-prompt-default")
async def memory_extract_prompt_default():
    from services.memory_engine import default_extract_prompt
    return {"prompt": default_extract_prompt()}


@router.get("/ha-tool-categories")
async def ha_tool_categories():
    from services.ha_tool_access import CATEGORY_KEYS
    return {"categories": CATEGORY_KEYS}


@router.get("/bridge-tool-groups")
async def bridge_tool_groups():
    from services.bridge_tool_access import GROUP_KEYS
    return {"groups": GROUP_KEYS}


@router.get("/secondary-use-for-categories")
async def secondary_use_for_categories():
    """Categories a secondary provider can be opted into for tool recall."""
    from services.secondary_routing import EXTRA_CATEGORY_KEYS, DEFAULT_USE_FOR
    from services.ha_tool_access import CATEGORY_KEYS

    return {
        "extra": EXTRA_CATEGORY_KEYS,
        "ha": CATEGORY_KEYS,
        "categories": use_for_labels(),
        "defaults": DEFAULT_USE_FOR,
    }


@router.get("/voice/voices")
async def voice_voices(language: str = ""):
    """Chirp 3: HD speakers for the Settings picker."""
    from services import google_voice as gv
    from services import voice as vc

    conf = vc.settings()
    lang = language or conf["language"]
    if not conf["google_api_key"]:
        return {"voices": [], "language": lang, "error": "No Google API key saved yet."}
    try:
        return {"voices": await gv.list_voices(conf["google_api_key"], lang), "language": lang}
    except gv.VoiceError as exc:
        return {"voices": [], "language": lang, "error": str(exc)}


@router.get("/voice/local/voices")
async def voice_local_voices(url: str = ""):
    """Voices advertised by a Wyoming TTS server (Piper), for the Settings picker."""
    from services import google_voice as gv
    from services import local_voice as lv
    from services import voice as vc

    target = url.strip() or vc.settings()["local_tts"]["url"]
    if not target:
        return {"voices": [], "url": target, "error": "No local text-to-speech URL saved yet."}
    try:
        info = await lv.describe(target, kind="tts", timeout=15)
    except gv.VoiceError as exc:
        return {"voices": [], "url": target, "error": str(exc)}
    return {"voices": lv.voices_from_info(info), "url": target}


@router.post("/voice/local/check")
async def voice_local_check(data: dict | None = None):
    """Ping a local Whisper/Piper server and report what it offers."""
    from services import google_voice as gv
    from services import local_voice as lv
    from services import voice as vc

    payload = data or {}
    kind = "stt" if str(payload.get("kind") or "").lower() == "stt" else "tts"
    conf = vc.settings()
    default_url = conf["local_stt"]["url"] if kind == "stt" else conf["local_tts"]["url"]
    target = str(payload.get("url") or "").strip() or default_url
    if not target:
        return JSONResponse(status_code=400, content={"error": "Add the server address first."})
    try:
        mode, host, port = lv.parse_endpoint(target, lv.DEFAULT_STT_PORT if kind == "stt" else lv.DEFAULT_TTS_PORT)
    except gv.VoiceError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    if mode == "http":
        # HTTP speech servers have no handshake; a real call is the only check.
        return {"ok": True, "mode": "http", "url": host, "detail": "OpenAI-compatible HTTP endpoint"}
    try:
        info = await lv.describe(target, kind=kind, timeout=15)
    except gv.VoiceError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
    if kind == "stt":
        models = lv.models_from_info(info)
        return {"ok": True, "mode": "wyoming", "url": f"{host}:{port}", "models": models}
    voices = lv.voices_from_info(info)
    return {"ok": True, "mode": "wyoming", "url": f"{host}:{port}", "voices": voices}


@router.post("/voice/test")
async def voice_test(data: dict | None = None):
    """Synthesize a short sample so the user can hear the voice before saving."""
    import base64

    from services import google_voice as gv
    from services import local_voice as lv
    from services import voice as vc

    payload = data or {}
    conf = vc.settings()
    language = str(payload.get("language") or conf["language"])
    sample = str(payload.get("text") or "").strip()
    if not sample:
        sample = (
            "Salut! Sunt HASSAI, asistentul tău pentru casă."
            if language.startswith("ro")
            else "Hi! I am HASSAI, your home assistant copilot."
        )
    # Same cleanup as spoken chat replies (so HASSAI is read as "Hassai", not H-A-S-S-A-I).
    sample = vc.speakable_text(sample, conf["max_reply_chars"])
    if not sample:
        return JSONResponse(status_code=400, content={"error": "Nothing to speak."})

    engine = str(payload.get("engine") or conf["tts_engine"]).strip().lower()
    if engine == "local":
        local = conf["local_tts"]
        url = str(payload.get("url") or "").strip() or local["url"]
        voice = str(payload.get("voice") or "").strip() or local["voice"]
        if not url:
            return JSONResponse(status_code=400, content={"error": "Add the local speech server address first."})
        try:
            audio, mime = await lv.synthesize(
                url, sample,
                voice=voice,
                speaker=str(payload.get("speaker") or local["speaker"]),
                model=str(payload.get("model") or local["model"]),
                timeout=local["timeout"],
            )
        except gv.VoiceError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        return {
            "ok": True,
            "text": sample,
            "voice": voice or url,
            "audio": f"data:{mime};base64," + base64.b64encode(audio).decode("ascii"),
        }

    api_key = str(payload.get("google_api_key") or "").strip() or conf["google_api_key"]
    speaker = str(payload.get("voice") or conf["voice"])
    if not api_key:
        return JSONResponse(status_code=400, content={"error": "Add a Google API key first."})
    try:
        audio = await gv.synthesize(
            api_key, sample,
            language=language, speaker=speaker,
            speaking_rate=conf["speaking_rate"],
        )
    except gv.VoiceError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
    return {
        "ok": True,
        "text": sample,
        "voice": gv.voice_name(language, speaker),
        "audio": "data:audio/mpeg;base64," + base64.b64encode(audio).decode("ascii"),
    }


@router.put("/")
async def update_settings(data: SettingsUpdate):
    cfg = load_config()
    if data.lmstudio is not None:
        cfg["lmstudio"].update(data.lmstudio)
    if data.searxng is not None:
        cfg["searxng"].update(data.searxng)
    if data.frigate is not None:
        cfg.setdefault("frigate", {}).update(data.frigate)
    if data.memory is not None:
        incoming = dict(data.memory)
        if isinstance(incoming.get("auto_consolidation"), dict):
            from services.consolidation_schedule import normalize_auto_consolidation
            prev = (cfg.get("memory") or {}).get("auto_consolidation") or {}
            merged = dict(prev) if isinstance(prev, dict) else {}
            merged.update(incoming["auto_consolidation"])
            if "last_run_at" not in incoming["auto_consolidation"]:
                merged["last_run_at"] = (prev or {}).get("last_run_at", 0) if isinstance(prev, dict) else 0
            incoming["auto_consolidation"] = normalize_auto_consolidation(merged)
        cfg["memory"].update(incoming)
    if data.voice is not None:
        incoming = dict(data.voice)
        # Blank key from the UI means "leave the stored one alone".
        if not str(incoming.get("google_api_key") or "").strip():
            incoming.pop("google_api_key", None)
        cfg.setdefault("voice", {}).update(incoming)
    if data.performance is not None:
        cfg.setdefault("performance", {}).update(data.performance)
    if data.security is not None:
        cfg.setdefault("security", {}).update(data.security)
    if data.system_prompt is not None:
        cfg["system_prompt"] = data.system_prompt
    if data.ha_agent_prompt is not None:
        cfg["ha_agent_prompt"] = data.ha_agent_prompt
    if data.knowledge_cutoff is not None:
        cfg["knowledge_cutoff"] = data.knowledge_cutoff
    if data.language is not None:
        cfg["language"] = data.language
    if data.dynamic_greetings is not None:
        cfg["dynamic_greetings"] = bool(data.dynamic_greetings)
    if data.greetings is not None:
        from services.greeting_pool import normalize_greetings_cfg
        prev = cfg.get("greetings") if isinstance(cfg.get("greetings"), dict) else {}
        merged = dict(prev)
        incoming = dict(data.greetings)
        # Preserve generation metadata unless explicitly sent.
        for key in ("last_generated_at", "last_season_key", "status", "error"):
            if key not in incoming:
                if key in prev:
                    merged[key] = prev[key]
        merged.update(incoming)
        cfg["greetings"] = normalize_greetings_cfg(merged)
    if data.ha_tools is not None:
        cfg.setdefault("ha_tools", {}).update(data.ha_tools)
    if data.bridge_tools is not None:
        cfg.setdefault("bridge_tools", {}).update(data.bridge_tools)
    if data.active_provider is not None:
        cfg["active_provider"] = data.active_provider
    if data.providers is not None:
        cfg["providers"] = data.providers
    if data.routing is not None:
        cfg.setdefault("routing", {}).update(data.routing)
    if data.pricing is not None:
        cfg.setdefault("pricing", {}).update(data.pricing)
    save_config(cfg)
    if data.routing is not None or data.providers is not None:
        # Role assignments and provider edits invalidate sticky sessions.
        from services import router as provider_router

        provider_router.reset_state()
    return {"status": "ok", "config": cfg}


@router.get("/greetings")
async def greetings_status():
    from services import greeting_pool as gp
    return gp.status_payload()


@router.post("/greetings/regenerate")
async def greetings_regenerate():
    """Force-refresh the LLM greeting pool with the configured provider/model."""
    from services import greeting_pool as gp
    return await gp.regenerate(force=True)


@router.put("/users/default")
async def set_default_user(data: dict):
    username = data.get("username", "").strip()
    cfg = load_config()
    cfg.setdefault("users", {})["default_user"] = username
    save_config(cfg)
    return {"status": "ok", "default_user": username}


@router.post("/users")
async def add_user(data: dict):
    from core.identity import ensure_user, list_profiles

    username = data.get("username", "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    if any(p["username"] == username for p in list_profiles()):
        raise HTTPException(status_code=409, detail="User already exists")
    return ensure_user(username, source="manual")


@router.get("/users/profiles")
async def user_profiles():
    from core.identity import list_profiles
    return {"users": list_profiles()}


@router.post("/users/sync-ha")
async def sync_ha_users():
    """Upsert Bridge users from HA person entities + anyone already seen via Ingress."""
    from core.identity import ensure_user, list_profiles

    created = []
    people = await ha_api.list_ha_people()
    for person in people:
        name = (person.get("name") or "").strip()
        if not name:
            continue
        row = ensure_user(
            name,
            ha_id=person.get("user_id") or "",
            display_name=name,
            source="home_assistant",
        )
        created.append(row)
    existing = {u["username"] for u in created}
    for row in list_profiles():
        if row["username"] not in existing:
            created.append(row)
    return {"users": created, "synced": len(people)}


@router.delete("/users/{username}")
async def delete_user(username: str, purge: bool = False):
    cfg = load_config()
    users = cfg.setdefault("users", {})
    api_keys = users.setdefault("api_keys", {})
    profiles = users.setdefault("profiles", {})
    to_remove = [k for k, v in api_keys.items() if v == username]
    for k in to_remove:
        del api_keys[k]
    if username in profiles:
        del profiles[username]
    save_config(cfg)
    # Cascade-delete all user data if purge requested
    data_deleted = {}
    if purge:
        data_deleted = delete_user_data(username)
    return {"status": "ok", "removed": len(to_remove), "data_deleted": data_deleted}


# ══════════════════════════════════════════════════
# Provider management endpoints
# ══════════════════════════════════════════════════

@router.get("/providers/presets")
async def get_provider_presets():
    """Return available provider type presets (base URLs, capabilities, etc.)."""
    from services.provider_capabilities import preset_capabilities

    out = {}
    for key, preset in PROVIDER_PRESETS.items():
        entry = dict(preset)
        caps = preset_capabilities(key)
        if caps:
            entry["capabilities"] = caps
        out[key] = entry
    return out


@router.get("/providers")
async def list_providers():
    """List all configured providers."""
    from services.provider_capabilities import provider_chat_capabilities

    cfg = load_config()
    providers = []
    for row in cfg.get("providers") or []:
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        enriched["capabilities"] = provider_chat_capabilities(row)
        providers.append(enriched)
    return {
        "providers": providers,
        "active_provider": cfg.get("active_provider", ""),
    }


@router.get("/routing")
async def get_routing():
    """Auto mode config plus what it would pick with the current providers."""
    from services import pricing as pr
    from services import router as provider_router

    cfg = load_config()
    conf = provider_router.routing_config(cfg)
    pool = [p for p in (cfg.get("providers") or []) if isinstance(p, dict) and p.get("id")]
    derived = provider_router.derive_roles(pool, cfg)
    return {
        "routing": conf,
        "roles_effective": {
            role: (conf["roles"].get(role) or (derived.get(role) or {}).get("id", ""))
            for role in provider_router.ROLES
        },
        "roles_derived": {
            role: (derived.get(role) or {}).get("id", "") for role in provider_router.ROLES
        },
        "tiers": {p["id"]: pr.tier(p, cfg) for p in pool},
        "pricing": pr.public_status(cfg),
        "unhealthy": provider_router.breaker_state(),
    }


def _clean_role_models(raw) -> dict:
    """Keep only the routing roles that pick a model, with trimmed values."""
    from services.router import ROLES

    if not isinstance(raw, dict):
        return {}
    return {
        role: str(raw.get(role) or "").strip()
        for role in ROLES
        if str(raw.get(role) or "").strip()
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
    if ptype == "grok":
        from services import grok as gk
        if gk.is_imagine_model(model):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{model}' is an Imagine image model. Use grok-4.6 (or another chat model) "
                    "for the provider Model — Imagine is used automatically for image generation."
                ),
            )
    if not base_url:
        preset = PROVIDER_PRESETS.get(ptype, {})
        base_url = preset.get("base_url", "http://localhost:1234")
    else:
        base_url = providers.normalize_provider_base_url(base_url)

    # Generate a stable ID from type + name (safe for HTML/JS attributes)
    pid = f"{ptype}_{_provider_id_slug(name)}"
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
        "role_models": _clean_role_models(data.get("role_models")),
        "secondary_provider": str(data.get("secondary_provider") or "").strip(),
        "vision_provider": str(data.get("vision_provider") or "").strip(),
        "image_generation_provider": str(data.get("image_generation_provider") or "").strip(),
        "thinking_mode": str(data.get("thinking_mode") or "auto").strip() or "auto",
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
            for key in ("name", "type", "base_url", "api_key", "model", "timeout", "max_tokens", "temperature", "system_prompt", "secondary_provider", "vision_provider", "image_generation_provider", "thinking_mode", "role_models"):
                if key in data:
                    val = data[key]
                    if key == "system_prompt" and isinstance(val, str):
                        val = val.strip()
                    elif key == "role_models":
                        val = _clean_role_models(val)
                    p[key] = val
            if p.get("base_url"):
                p["base_url"] = providers.normalize_provider_base_url(p["base_url"])
            if (p.get("type") or data.get("type")) == "grok":
                from services import grok as gk
                mid = str(p.get("model") or "").strip()
                if gk.is_imagine_model(mid):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"'{mid}' is an Imagine image model. Use grok-4.6 (or another chat model) "
                            "for the provider Model — Imagine is used automatically for image generation."
                        ),
                    )
            save_config(cfg)
            # Role-model edits must not leave sticky sessions on the old role.
            from services import router as provider_router

            provider_router.reset_state()
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


# ══════════════════════════════════════════════════
# Secondary provider management endpoints
# ══════════════════════════════════════════════════

@router.get("/secondary-providers")
async def list_secondary_providers():
    """List all configured secondary providers."""
    cfg = load_config()
    return {"secondary_providers": cfg.get("secondary_providers", [])}


@router.post("/secondary-providers")
async def add_secondary_provider(data: dict):
    """Add a new secondary provider."""
    ptype = data.get("type", "local")
    name = data.get("name", "").strip()
    base_url = data.get("base_url", "").strip()
    api_key = data.get("api_key", "").strip()
    model = data.get("model", "default").strip()
    timeout = data.get("timeout", 120)
    max_tokens = data.get("max_tokens", 2048)
    temperature = data.get("temperature", 0.7)

    if not name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    if not base_url:
        preset = PROVIDER_PRESETS.get(ptype, {})
        base_url = preset.get("base_url", "http://localhost:1234")
    else:
        base_url = providers.normalize_provider_base_url(base_url)

    pid = f"sec_{ptype}_{_provider_id_slug(name)}"
    cfg = load_config()
    existing_ids = {p["id"] for p in cfg.get("secondary_providers", [])}
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
        "use_for": normalize_use_for(data.get("use_for")),
    }
    cfg.setdefault("secondary_providers", []).append(provider)
    save_config(cfg)
    return {"status": "ok", "provider": provider}


@router.put("/secondary-providers/{provider_id}")
async def update_secondary_provider(provider_id: str, data: dict):
    """Update an existing secondary provider."""
    cfg = load_config()
    for p in cfg.get("secondary_providers", []):
        if p["id"] == provider_id:
            for key in ("name", "type", "base_url", "api_key", "model", "timeout", "max_tokens", "temperature"):
                if key in data:
                    p[key] = data[key]
            if "use_for" in data:
                p["use_for"] = normalize_use_for(data.get("use_for"))
            if p.get("base_url"):
                p["base_url"] = providers.normalize_provider_base_url(p["base_url"])
            save_config(cfg)
            return {"status": "ok", "provider": p}
    raise HTTPException(status_code=404, detail="Secondary provider not found")


@router.delete("/secondary-providers/{provider_id}")
async def delete_secondary_provider(provider_id: str):
    """Delete a secondary provider. Also clears references from primary providers."""
    cfg = load_config()
    plist = cfg.get("secondary_providers", [])
    cfg["secondary_providers"] = [p for p in plist if p["id"] != provider_id]
    # Clear references from primary providers
    for p in cfg.get("providers", []):
        if p.get("secondary_provider") == provider_id:
            p["secondary_provider"] = ""
        if p.get("vision_provider") == provider_id:
            p["vision_provider"] = ""
        if p.get("image_generation_provider") == provider_id:
            p["image_generation_provider"] = ""
    save_config(cfg)
    return {"status": "ok"}


@router.get("/secondary-providers/{provider_id}/models")
async def get_secondary_provider_models(provider_id: str):
    """List models available on a specific secondary provider."""
    cfg = load_config()
    for p in cfg.get("secondary_providers", []):
        if p["id"] == provider_id:
            try:
                models = await providers.list_models(p)
                return {"models": models}
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Could not reach provider: {e}")
    raise HTTPException(status_code=404, detail="Secondary provider not found")


@router.get("/secondary-providers/{provider_id}/health")
async def check_secondary_provider_health(provider_id: str):
    """Health check for a specific secondary provider."""
    cfg = load_config()
    for p in cfg.get("secondary_providers", []):
        if p["id"] == provider_id:
            ok = await providers.health_check(p)
            return {"status": "connected" if ok else "unreachable", "provider": p["name"]}
    raise HTTPException(status_code=404, detail="Secondary provider not found")


@router.get("/health")
async def health():
    active = get_active_provider()
    from services import frigate_tools as ft

    provider_ok, sx_ok, fr = await asyncio.gather(
        providers.health_check(active),
        searxng.health_check(),
        ft.health_status(),
    )
    return {
        "provider": "connected" if provider_ok else "unreachable",
        "provider_name": active.get("name", "?"),
        "provider_type": active.get("type", "?"),
        # Keep lmstudio key for backward compatibility
        "lmstudio": "connected" if provider_ok else "unreachable",
        "searxng": "connected" if sx_ok else "unreachable",
        "frigate": fr.get("status") or "unreachable",
    }


@router.get("/frigate/health")
async def frigate_health():
    """Test Frigate API connectivity (uses saved settings)."""
    from services import frigate_tools as ft

    fr = await ft.health_status(probe_timeout=5.0)
    cameras: list[str] = []
    if fr.get("status") == "connected" and fr.get("via") == "api":
        try:
            data = await asyncio.wait_for(ft._get_json("/api/config"), timeout=5.0)
            cameras = sorted((data.get("cameras") or {}).keys())
        except Exception:
            cameras = []
    return {
        "status": fr.get("status") or "unreachable",
        "url": fr.get("url") or ft.base_url(),
        "enabled": bool(fr.get("enabled")),
        "via": fr.get("via") or "",
        "cameras": cameras,
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

    from services import frigate_tools as ft

    async def _ha_ping():
        if ha_api.is_available():
            return await ha_api.ping()
        return False, "standalone"

    lm_ok, sx_ok, fr, ha_ping = await asyncio.gather(
        providers.health_check(),
        searxng.health_check(),
        ft.health_status(),
        _ha_ping(),
    )
    fr_status = fr.get("status") or "unreachable"
    fr_enabled = bool(fr.get("enabled"))
    active = get_active_provider()
    ha_connected, ha_detail = ha_ping

    # Mask API keys in response (#10)
    safe_providers = []
    for p in cfg.get("providers", []):
        sp = dict(p)
        if sp.get("api_key"):
            sp["api_key"] = _mask_key(sp["api_key"])
        safe_providers.append(sp)

    safe_secondary = []
    for p in cfg.get("secondary_providers", []):
        sp = dict(p)
        if sp.get("api_key"):
            sp["api_key"] = _mask_key(sp["api_key"])
        safe_secondary.append(sp)

    return {
        "version": VERSION,
        "build": BUILD_ID,
        "language": cfg.get("language") or "en",
        "uptime_seconds": round(uptime),
        "api_key": _mask_key(cfg.get("api_key", "")),
        "local_ip": _get_local_ip(),
        "port": 8899,
        "home_assistant": {
            "available": ha_api.is_available(),
            "connected": ha_connected,
            "detail": ha_detail,
            "tools": sorted(ha_api.ha_tool_names(cfg)) if ha_api.is_available() else [],
        },
        "active_provider": cfg.get("active_provider", ""),
        "providers": safe_providers,
        "secondary_providers": safe_secondary,
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
            "frigate": {
                "status": fr_status,
                "enabled": fr_enabled,
                "url": fr.get("url") or ft.base_url(),
                "via": fr.get("via") or "",
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
            {"method": "GET", "path": "/v1/chat/activity/{trace_id}", "description": "Live agent tool steps"},
            {"method": "POST", "path": "/v1/chat/cancel/{trace_id}", "description": "Cancel in-flight chat/agent trace"},
            {"method": "GET", "path": "/v1/models", "description": "List Models (OpenAI)"},
            {"method": "GET", "path": "/api/settings/", "description": "Get Settings"},
            {"method": "PUT", "path": "/api/settings/", "description": "Update Settings"},
            {"method": "GET", "path": "/api/settings/health", "description": "Health Check"},
            {"method": "GET", "path": "/api/settings/info", "description": "System Info"},
            {"method": "GET", "path": "/api/settings/stats", "description": "Usage Statistics"},
            {"method": "POST", "path": "/api/settings/restart", "description": "Restart Server"},
            {"method": "GET", "path": "/api/me", "description": "Current HA / Bridge user"},
            {"method": "GET", "path": "/api/conversations", "description": "List current user chats"},
            {"method": "POST", "path": "/api/conversations", "description": "Start a new chat"},
            {"method": "GET", "path": "/api/conversations/{session_id}", "description": "Get chat messages"},
            {"method": "DELETE", "path": "/api/conversations/{session_id}", "description": "Delete a chat"},
            {"method": "POST", "path": "/api/settings/users", "description": "Add User + Generate API Key"},
            {"method": "GET", "path": "/api/settings/users/profiles", "description": "List Users + HA profiles"},
            {"method": "POST", "path": "/api/settings/users/sync-ha", "description": "Sync users from HA person entities"},
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
            {"method": "GET", "path": "/api/settings/secondary-providers", "description": "List Secondary Providers"},
            {"method": "POST", "path": "/api/settings/secondary-providers", "description": "Add Secondary Provider"},
            {"method": "PUT", "path": "/api/settings/secondary-providers/{id}", "description": "Update Secondary Provider"},
            {"method": "DELETE", "path": "/api/settings/secondary-providers/{id}", "description": "Delete Secondary Provider"},
            {"method": "GET", "path": "/api/settings/secondary-providers/{id}/models", "description": "Secondary Provider Models"},
            {"method": "GET", "path": "/api/settings/secondary-providers/{id}/health", "description": "Secondary Provider Health"},
            {"method": "GET", "path": "/api/settings/conversations/{user_id}", "description": "List Conversation Sessions"},
            {"method": "GET", "path": "/api/settings/conversations/{user_id}/{session_id}", "description": "Get Session Messages"},
            {"method": "DELETE", "path": "/api/settings/conversations/{user_id}/{session_id}", "description": "Delete Session"},
            {"method": "POST", "path": "/api/settings/conversations/{user_id}/bulk-delete", "description": "Bulk Delete Sessions"},
            {"method": "GET", "path": "/api/settings/export", "description": "Download full settings export (ZIP)"},
            {"method": "POST", "path": "/api/settings/import/upload", "description": "Restore full settings from ZIP"},
            {"method": "GET", "path": "/api/settings/import/share", "description": "List ZIP/DB files under /share and /media"},
            {"method": "POST", "path": "/api/settings/import/share", "description": "Restore from a /share or /media path"},
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
            {"method": "POST", "path": "/api/memory/bulk-delete", "description": "Bulk Delete Memories"},
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
            {"method": "GET", "path": "/api/skills/", "description": "List Skills"},
            {"method": "GET", "path": "/api/skills/template", "description": "Skill Template"},
            {"method": "POST", "path": "/api/skills/", "description": "Create Skill"},
            {"method": "GET", "path": "/api/skills/{skill_name}", "description": "Get Skill Source"},
            {"method": "PATCH", "path": "/api/skills/{skill_name}", "description": "Update Skill"},
            {"method": "DELETE", "path": "/api/skills/{skill_name}", "description": "Delete Skill"},
            {"method": "POST", "path": "/api/skills/{skill_name}/toggle", "description": "Toggle Skill"},
            {"method": "POST", "path": "/api/skills/{skill_name}/test", "description": "Test Skill"},
            {"method": "POST", "path": "/api/skills/reload", "description": "Reload All Skills"},
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


@router.post("/conversations/{user_id}/bulk-delete")
async def bulk_delete_sessions(user_id: str, data: dict):
    """Delete multiple conversation sessions."""
    session_ids = data.get("session_ids", [])
    if not session_ids or not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids list required")
    deleted = bulk_delete_conversation_sessions(user_id, session_ids)
    return {"status": "ok", "deleted": deleted}


# ══════════════════════════════════════════════════
# Full export / import (config + DB + uploads + skills)
# ══════════════════════════════════════════════════

@router.get("/export")
async def export_full():
    """Download a full ZIP: config, database, chat uploads, generated skills."""
    import tempfile
    from datetime import datetime, timezone
    from fastapi.responses import FileResponse as FR

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        ei_export.build_export_zip(tmp_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}") from e

    def _cleanup():
        tmp_path.unlink(missing_ok=True)

    return FR(
        path=str(tmp_path),
        filename=f"hassai-export-{stamp}.zip",
        media_type="application/zip",
        background=BackgroundTask(_cleanup),
    )


@router.get("/export/config")
async def export_config_only():
    """Download settings-only JSON (providers, profiles, keys — no database)."""
    import json as _json
    from datetime import datetime, timezone
    from fastapi.responses import Response

    cfg = load_config()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    body = _json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="hassai-settings-{stamp}.json"',
        },
    )


@router.post("/import/config")
async def import_config_only(data: dict):
    """Restore settings/profiles/providers from a JSON object (Ingress-safe)."""
    try:
        return ei_export.restore_config_only(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e


@router.post("/import/start")
async def import_chunk_start(data: dict):
    """Start a chunked upload (zip or db) — avoids HA Ingress body size limits."""
    try:
        size = int(data.get("size") or 0)
        kind = str(data.get("kind") or "zip").strip().lower() or "zip"
        return ei_export.start_chunked_upload(
            size=size,
            filename=str(data.get("filename") or ""),
            kind=kind,
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/import/chunk")
async def import_chunk_upload(
    id: str = Form(...),
    offset: int = Form(...),
    chunk: UploadFile = FastAPIFile(...),
):
    """Append one binary chunk of a ZIP export."""
    data = await chunk.read()
    try:
        return ei_export.append_chunk(id, int(offset), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/import/finish")
async def import_chunk_finish(data: dict):
    """Finalize chunked ZIP upload and restore."""
    upload_id = str(data.get("id") or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="id required")
    try:
        return ei_export.finish_chunked_upload(upload_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e


@router.post("/import/upload")
async def import_full_upload(file: UploadFile = FastAPIFile(...)):
    """Restore full settings and data from a HASSAI export ZIP (small files / non-Ingress)."""
    import tempfile

    name = (file.filename or "").lower()
    if not name.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip export files are accepted")

    contents = await file.read()
    if len(contents) > ei_export.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 200MB)")
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        result = ei_export.restore_export_zip(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    return result


@router.get("/import/share")
async def list_share_imports():
    """List ZIP/DB files in /share top-level only (safe — no /media recursion)."""
    try:
        files = ei_export.list_share_import_files()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {e}") from e
    root = ei_export._share_root()
    return {
        "files": files,
        "roots": [str(root)] if root.exists() else [],
        "default_name": ei_export.DEFAULT_SHARE_IMPORT_NAME,
    }


@router.post("/import/share")
async def import_from_share(data: dict):
    """Restore from a file already on /share (filename only — no WebView upload)."""
    raw = str((data or {}).get("path") or (data or {}).get("name") or "").strip()
    try:
        return ei_export.import_from_share_path(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e


# ══════════════════════════════════════════════════
# Database backup / restore (legacy .db only)
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



@router.post("/restore/upload")
async def restore_database_upload(file: UploadFile = FastAPIFile(...)):
    """Restore database from uploaded .db file (legacy single-shot; prefer chunked import)."""
    import tempfile

    if not file.filename or not file.filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="Only .db files are accepted")

    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        return ei_export.restore_database_file(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)
