"""Map Home Assistant ingress users ↔ Bridge usernames + Assist API keys."""

from __future__ import annotations

from fastapi import Request

from core.config import _generate_api_key, load_config, save_config


INGRESS_USER_HEADERS = (
    "x-remote-user-name",
    "x-remote-user-id",
    "x-remote-user-display-name",
    "x-hass-user-id",
    "x-hass-user-name",
    "x-ha-username",
    "x-ha-user-name",
    "x-ha-user-id",
    "x-ha-user",
)


def ingress_identity(request: Request) -> dict:
    """Read HA Ingress / legacy HA headers."""
    headers = request.headers
    ha_id = (
        headers.get("x-remote-user-id")
        or headers.get("x-hass-user-id")
        or headers.get("x-ha-user-id")
        or ""
    ).strip()
    username = (
        headers.get("x-remote-user-name")
        or headers.get("x-hass-user-name")
        or headers.get("x-ha-username")
        or headers.get("x-ha-user-name")
        or ""
    ).strip()
    display = (
        headers.get("x-remote-user-display-name")
        or headers.get("x-ha-user")
        or username
        or ""
    ).strip()
    return {"ha_id": ha_id, "username": username, "display_name": display}


def _slug(name: str, ha_id: str) -> str:
    raw = (name or "").strip()
    if raw:
        return raw
    if ha_id:
        return f"ha_{ha_id.replace('-', '')[:12]}"
    return ""


def _key_for_username(api_keys: dict, username: str) -> str:
    for key, name in api_keys.items():
        if name == username:
            return key
    return ""


def ensure_user(username: str, *, ha_id: str = "", display_name: str = "", source: str = "manual") -> dict:
    """Create or update a Bridge user. Returns {username, api_key, ha_id, display_name, source}."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username required")
    cfg = load_config()
    users = cfg.setdefault("users", {"default_user": "", "api_keys": {}, "profiles": {}})
    api_keys = users.setdefault("api_keys", {})
    profiles = users.setdefault("profiles", {})

    # Reuse username already bound to this HA id
    if ha_id:
        for uname, prof in profiles.items():
            if isinstance(prof, dict) and prof.get("ha_id") == ha_id:
                username = uname
                break

    changed = False
    api_key = _key_for_username(api_keys, username)
    if not api_key:
        api_key = _generate_api_key()
        api_keys[api_key] = username
        changed = True

    prof = dict(profiles.get(username)) if isinstance(profiles.get(username), dict) else {}
    if ha_id and prof.get("ha_id") != ha_id:
        prof["ha_id"] = ha_id
        changed = True
    if display_name and prof.get("display_name") != display_name:
        prof["display_name"] = display_name
        changed = True
    if not prof.get("source"):
        prof["source"] = source
        changed = True
    if profiles.get(username) != prof:
        profiles[username] = prof
        changed = True

    if not users.get("default_user"):
        users["default_user"] = username
        changed = True

    if changed:
        save_config(cfg)
    return {
        "username": username,
        "api_key": api_key,
        "ha_id": prof.get("ha_id", ha_id),
        "display_name": prof.get("display_name") or display_name or username,
        "source": prof.get("source", source),
    }


def ensure_from_request(request: Request) -> dict | None:
    ident = ingress_identity(request)
    username = _slug(ident["username"] or ident["display_name"], ident["ha_id"])
    if not username:
        return None
    return ensure_user(
        username,
        ha_id=ident["ha_id"],
        display_name=ident["display_name"] or ident["username"] or username,
        source="home_assistant",
    )


def list_profiles() -> list[dict]:
    cfg = load_config()
    users = cfg.get("users", {})
    api_keys = users.get("api_keys", {})
    profiles = users.get("profiles", {})
    by_name: dict[str, dict] = {}
    for key, name in api_keys.items():
        by_name[name] = {
            "username": name,
            "api_key": key,
            "ha_id": "",
            "display_name": name,
            "source": "manual",
        }
    for name, prof in (profiles or {}).items():
        if not isinstance(prof, dict):
            continue
        row = by_name.setdefault(name, {
            "username": name,
            "api_key": _key_for_username(api_keys, name),
            "ha_id": "",
            "display_name": name,
            "source": "manual",
        })
        row.update({
            "ha_id": prof.get("ha_id") or row.get("ha_id", ""),
            "display_name": prof.get("display_name") or row.get("display_name") or name,
            "source": prof.get("source") or row.get("source") or "manual",
        })
    return sorted(by_name.values(), key=lambda r: r["username"].lower())


def get_profile(username: str) -> dict | None:
    username = (username or "").strip()
    if not username:
        return None
    for row in list_profiles():
        if row.get("username") == username:
            return row
    return None


def resolve_display_name(username: str, request: Request | None = None) -> str:
    """Best display name for a Bridge user (ingress headers, then stored profile)."""
    username = (username or "").strip()
    if not username or username in ("default", "webui"):
        return ""

    if request is not None:
        profile = ensure_from_request(request)
        if profile and profile.get("username") == username:
            name = (profile.get("display_name") or "").strip()
            if name and name not in ("default", "webui"):
                return name

    prof = get_profile(username)
    if prof:
        name = (prof.get("display_name") or prof.get("username") or "").strip()
        if name and name not in ("default", "webui"):
            return name

    if not username.startswith("ha_"):
        return username.replace("_", " ")
    return ""


def user_context_for_prompt(username: str, request: Request | None = None) -> str:
    display = resolve_display_name(username, request)
    if not display:
        return ""
    return (
        "[User]\n"
        f"You are assisting {display} (Home Assistant user). "
        "Know their name for context, but do NOT address them by name in every reply — "
        "it sounds unnatural. Prefer plain answers with no name. "
        "Use the name only rarely (e.g. a warm opening on a new chat, or when it clearly helps). "
        "Never start most replies with their name. Match their language."
    )
