"""Home Assistant Core API client (add-on via Supervisor proxy).

When the bridge runs as a HA add-on with `homeassistant_api: true`, Supervisor
injects SUPERVISOR_TOKEN. Requests go to http://supervisor/core/api/...
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("hassai.ha")

_SUPERVISOR = "http://supervisor"
_TIMEOUT = 30.0

# Domains shown by default in list results (keeps context small)
_DEFAULT_DOMAINS = (
    "light", "switch", "climate", "cover", "fan", "lock", "media_player",
    "vacuum", "scene", "script", "input_boolean", "input_button",
    "binary_sensor", "sensor", "automation", "person", "device_tracker",
)


def is_available() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN", "").strip())


def _headers() -> dict[str, str]:
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _request(method: str, path: str, **kwargs) -> Any:
    if not is_available():
        raise RuntimeError("Home Assistant API unavailable (not running as HA add-on)")
    url = f"{_SUPERVISOR}/core/api{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, url, headers=_headers(), **kwargs)
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise RuntimeError(f"HA API {resp.status_code}: {detail}")
        if resp.status_code == 204 or not resp.content:
            return {"ok": True}
        return resp.json()


def build_ha_tools() -> list[dict]:
    """OpenAI-style tool definitions for Home Assistant control."""
    if not is_available():
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": "ha_list_entities",
                "description": (
                    "List Home Assistant entities with current state. "
                    "Filter by domain and/or search text (name/entity_id)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "description": "Optional domain filter, e.g. light, switch, climate, sensor.",
                        },
                        "search": {
                            "type": "string",
                            "description": "Optional substring match on entity_id or friendly_name.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max entities to return (default 40, max 80).",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_get_state",
                "description": "Get the full state and attributes of one Home Assistant entity.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {
                            "type": "string",
                            "description": "Entity id, e.g. light.living_room.",
                        },
                    },
                    "required": ["entity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_call_service",
                "description": (
                    "Call a Home Assistant service to control devices "
                    "(e.g. light.turn_on, switch.turn_off, climate.set_temperature). "
                    "Only call when the user clearly wants an action."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "description": "Service domain, e.g. light, switch, homeassistant.",
                        },
                        "service": {
                            "type": "string",
                            "description": "Service name, e.g. turn_on, turn_off, toggle.",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "Target entity_id (preferred).",
                        },
                        "data": {
                            "type": "object",
                            "description": "Extra service data (brightness, temperature, etc.).",
                        },
                    },
                    "required": ["domain", "service"],
                },
            },
        },
    ]


def ha_system_hint() -> str:
    if not is_available():
        return ""
    return (
        "Home Assistant tools are available: ha_list_entities, ha_get_state, ha_call_service. "
        "Use them to read and control the smart home. "
        "Prefer looking up entities before calling services. "
        "Do not call services unless the user asked for an action."
    )


async def run_ha_tool(name: str, args: dict) -> str:
    """Execute a HA tool and return a short text result for the model."""
    try:
        if name == "ha_list_entities":
            return await _list_entities(args or {})
        if name == "ha_get_state":
            entity_id = (args.get("entity_id") or "").strip()
            if not entity_id:
                return "Error: entity_id is required"
            state = await _request("GET", f"/states/{entity_id}")
            return _format_state(state)
        if name == "ha_call_service":
            return await _call_service(args or {})
        return f"Error: unknown HA tool '{name}'"
    except Exception as e:
        log.error("HA tool %s failed: %s", name, e)
        return f"Error: {e}"


def _format_state(state: dict) -> str:
    eid = state.get("entity_id", "?")
    attrs = state.get("attributes") or {}
    name = attrs.get("friendly_name") or eid
    lines = [
        f"entity_id: {eid}",
        f"name: {name}",
        f"state: {state.get('state')}",
    ]
    # Keep attributes compact
    skip = {"friendly_name", "supported_features", "attribution"}
    interesting = {k: v for k, v in attrs.items() if k not in skip}
    if interesting:
        # Cap attribute dump
        items = list(interesting.items())[:20]
        attr_txt = ", ".join(f"{k}={v!r}" for k, v in items)
        lines.append(f"attributes: {attr_txt}")
    return "\n".join(lines)


async def _list_entities(args: dict) -> str:
    domain = (args.get("domain") or "").strip().lower()
    search = (args.get("search") or "").strip().lower()
    try:
        limit = int(args.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    limit = max(1, min(limit, 80))

    states = await _request("GET", "/states")
    if not isinstance(states, list):
        return "Error: unexpected states payload"

    rows: list[str] = []
    for st in states:
        eid = st.get("entity_id") or ""
        if domain and not eid.startswith(domain + "."):
            continue
        if not domain and not search:
            # Default: only common controllable / useful domains
            d = eid.split(".", 1)[0]
            if d not in _DEFAULT_DOMAINS:
                continue
        attrs = st.get("attributes") or {}
        fname = str(attrs.get("friendly_name") or "")
        if search and search not in eid.lower() and search not in fname.lower():
            continue
        area = attrs.get("area_id") or ""
        rows.append(f"{eid}|{fname}|{st.get('state')}|{area}")
        if len(rows) >= limit:
            break

    if not rows:
        return "No matching entities."
    header = "entity_id|name|state|area"
    return header + "\n" + "\n".join(rows)


async def _call_service(args: dict) -> str:
    domain = (args.get("domain") or "").strip()
    service = (args.get("service") or "").strip()
    if not domain or not service:
        return "Error: domain and service are required"

    data = dict(args.get("data") or {})
    entity_id = (args.get("entity_id") or "").strip()
    if entity_id:
        data["entity_id"] = entity_id

    await _request("POST", f"/services/{domain}/{service}", json=data)
    target = entity_id or data.get("entity_id") or "(no entity_id)"
    return f"OK: called {domain}.{service} on {target}"
