"""Per-conversation chat provider / model overrides.

Chat UI picks must stay on the current session — never rewrite the global
``active_provider`` or provider ``model`` in config (that would affect every user).
"""

from __future__ import annotations

import time

# session_id -> {provider_id, model, auto, ts}
_overrides: dict[str, dict] = {}

# Keep overrides around for the life of a sticky chat.
_TTL_SEC = 24 * 60 * 60
_MAX_ENTRIES = 2000


def _prune(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    stale = [sid for sid, row in _overrides.items() if now - float(row.get("ts") or 0) > _TTL_SEC]
    for sid in stale:
        _overrides.pop(sid, None)
    if len(_overrides) > _MAX_ENTRIES:
        oldest = sorted(_overrides.items(), key=lambda kv: float(kv[1].get("ts") or 0))
        for sid, _ in oldest[: len(_overrides) - _MAX_ENTRIES]:
            _overrides.pop(sid, None)


def clear(session_id: str | None) -> None:
    sid = str(session_id or "").strip()
    if sid:
        _overrides.pop(sid, None)
        try:
            from core import database as db

            db.clear_session_state(sid, db.KIND_CHAT_OVERRIDE)
        except Exception:
            pass


def get(session_id: str | None, user_id: str = "") -> dict | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    _prune()
    row = _overrides.get(sid)
    if row and time.time() - float(row.get("ts") or 0) <= _TTL_SEC:
        return {
            "provider_id": str(row.get("provider_id") or "").strip(),
            "model": str(row.get("model") or "").strip(),
            "auto": bool(row.get("auto")),
        }
    if row:
        _overrides.pop(sid, None)
    try:
        from core import database as db

        data = db.get_session_state(user_id, sid, db.KIND_CHAT_OVERRIDE)
        if not data:
            return None
        out = {
            "provider_id": str(data.get("provider_id") or "").strip(),
            "model": str(data.get("model") or "").strip(),
            "auto": bool(data.get("auto")),
        }
        _overrides[sid] = {**out, "ts": float(data.get("ts") or time.time())}
        return out
    except Exception:
        return None


def set_override(
    session_id: str | None,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    auto: bool | None = None,
    user_id: str = "",
) -> dict:
    """Upsert session override. Passing auto=True clears a manual provider pick."""
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id required")
    _prune()
    prev = dict(_overrides.get(sid) or {}) or (get(sid, user_id) or {})
    if auto is True:
        row = {
            "provider_id": "",
            "model": "",
            "auto": True,
            "ts": time.time(),
        }
    else:
        row = {
            "provider_id": (
                str(provider_id).strip()
                if provider_id is not None
                else str(prev.get("provider_id") or "").strip()
            ),
            "model": (
                str(model).strip()
                if model is not None
                else str(prev.get("model") or "").strip()
            ),
            "auto": False if auto is False or provider_id or model else bool(prev.get("auto")),
            "ts": time.time(),
        }
        if auto is False:
            row["auto"] = False
        if provider_id is not None or model is not None:
            row["auto"] = False
    _overrides[sid] = row
    try:
        from core import database as db

        db.upsert_session_state(
            user_id,
            sid,
            db.KIND_CHAT_OVERRIDE,
            {
                "provider_id": row["provider_id"],
                "model": row["model"],
                "auto": row["auto"],
                "ts": row["ts"],
            },
        )
    except Exception:
        pass
    return get(sid, user_id) or {"provider_id": "", "model": "", "auto": False}


def _active_from_cfg(cfg: dict | None) -> dict:
    from services.providers import get_active_provider

    if not isinstance(cfg, dict):
        return get_active_provider()
    pool = [p for p in (cfg.get("providers") or []) if isinstance(p, dict)]
    active_id = str(cfg.get("active_provider") or "").strip()
    for p in pool:
        if p.get("id") == active_id:
            return p
    if pool:
        return pool[0]
    return get_active_provider()


def resolve_route_for_session(
    cfg: dict,
    *,
    session_id: str = "",
    active: dict | None = None,
    user_text: str = "",
    has_images: bool = False,
    tools_active: bool = False,
    prompt_tokens: int = 0,
) -> dict:
    """Like router.resolve, but honors a session override when present."""
    from services import router as provider_router

    active = active if isinstance(active, dict) else _active_from_cfg(cfg)
    override = get(session_id)

    if override and override.get("auto"):
        conf = provider_router.routing_config(cfg)
        cfg_auto = dict(cfg)
        cfg_auto["routing"] = {**conf, "mode": "auto"}
        return provider_router.resolve(
            cfg_auto,
            active=active,
            session_id=session_id,
            user_text=user_text,
            has_images=has_images,
            tools_active=tools_active,
            prompt_tokens=prompt_tokens,
        )

    if override and (override.get("provider_id") or override.get("model")):
        pool = [p for p in (cfg.get("providers") or []) if isinstance(p, dict)]
        chosen = None
        pid = override.get("provider_id") or ""
        if pid:
            for p in pool:
                if p.get("id") == pid:
                    chosen = dict(p)
                    break
        if chosen is None:
            chosen = dict(active) if isinstance(active, dict) else {}
        mid = override.get("model") or ""
        if mid:
            chosen["model"] = mid
        klass = provider_router.classify(
            user_text, has_images=has_images, tools_active=tools_active,
        )
        return {
            "provider": chosen,
            "model": chosen.get("model", ""),
            "klass": klass,
            "role": "",
            "reason": "session",
            "auto": False,
        }

    return provider_router.resolve(
        cfg,
        active=active,
        session_id=session_id,
        user_text=user_text,
        has_images=has_images,
        tools_active=tools_active,
        prompt_tokens=prompt_tokens,
    )


def effective_chat_info(cfg: dict, session_id: str | None = None, user_id: str = "") -> dict:
    """Public chat block for /api/me (global default + optional session override)."""
    from services import router as provider_router
    from services import tool_profiles as tp
    from services import toolkits as tk
    from services.provider_capabilities import provider_chat_capabilities

    active = _active_from_cfg(cfg)
    override = get(session_id, user_id)
    global_auto = provider_router.is_auto(cfg)
    tool_profile = tp.tool_profile_mode(cfg)
    active_packs: list[str] = []
    if tool_profile == tp.PROFILE_DYNAMIC and session_id:
        active_packs = sorted(tk.get_sticky(session_id, user_id))

    base_extra = {
        "tool_profile": tool_profile,
        "active_packs": active_packs,
    }

    if override and override.get("auto"):
        return {
            "provider_id": active.get("id", ""),
            "provider_type": active.get("type", ""),
            "provider_name": active.get("name", ""),
            "model": active.get("model", ""),
            "thinking_mode": active.get("thinking_mode") or "auto",
            "capabilities": provider_chat_capabilities(active),
            "auto": True,
            "session_scoped": True,
            **base_extra,
        }

    if override and (override.get("provider_id") or override.get("model")):
        pool = [p for p in (cfg.get("providers") or []) if isinstance(p, dict)]
        chosen = active
        pid = override.get("provider_id") or ""
        if pid:
            for p in pool:
                if p.get("id") == pid:
                    chosen = p
                    break
        model = override.get("model") or chosen.get("model", "")
        view = dict(chosen)
        view["model"] = model
        return {
            "provider_id": view.get("id", ""),
            "provider_type": view.get("type", ""),
            "provider_name": view.get("name", ""),
            "model": model,
            "thinking_mode": view.get("thinking_mode") or "auto",
            "capabilities": provider_chat_capabilities(view),
            "auto": False,
            "session_scoped": True,
            **base_extra,
        }

    return {
        "provider_id": active.get("id", ""),
        "provider_type": active.get("type", ""),
        "provider_name": active.get("name", ""),
        "model": active.get("model", ""),
        "thinking_mode": active.get("thinking_mode") or "auto",
        "capabilities": provider_chat_capabilities(active),
        "auto": global_auto,
        "session_scoped": False,
        **base_extra,
    }
