"""Home Assistant admin client (add-on via Supervisor).

Uses SUPERVISOR_TOKEN:
- Core REST API  → http://supervisor/core/api/...
- Supervisor API → http://supervisor/...
- HA config dir  → /config  (when homeassistant_config is mapped)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable
from urllib.parse import urlencode

import httpx
import yaml

from . import lovelace_tools as lt
from . import entity_tools as et

_DASHBOARD_URL = {
    "type": "string",
    "description": "Optional HA URL (/lovelace/kitchen or /dashboard-energy/home) to fill url_path/view_path",
}

log = logging.getLogger("hassai.ha")

_SUPERVISOR = "http://supervisor"
_TIMEOUT = 45.0
_LOG_TIMEOUT = 60.0
_MAX_JSON = 14_000
_HA_CONFIG = Path("/config")
_ALLOWED_FILE_SUFFIXES = {".yaml", ".yml", ".json", ".txt", ".log", ".conf", ".cfg"}

_DEFAULT_DOMAINS = et._LEGACY_DEFAULT_DOMAINS

_STATES_CACHE: dict[str, Any] = {"ts": 0.0, "rows": None}
_STATES_CACHE_TTL = 8.0
_REGISTRY_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "entities": None,
    "areas": None,
    "devices": None,
    "labels": None,
    "floors": None,
}
_REGISTRY_CACHE_TTL = 30.0


def is_available() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN", "").strip())


def _headers() -> dict[str, str]:
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _dump(obj: Any, max_chars: int = _MAX_JSON) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n… truncated ({len(text)} chars). Narrow the request."
    return text


async def _http(
    method: str,
    url: str,
    *,
    json_body: Any | None = None,
    text: bool = False,
    timeout: float = _TIMEOUT,
) -> Any:
    if not is_available():
        raise RuntimeError("Home Assistant API unavailable (not running as HA add-on)")
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method, url, headers=_headers(), json=json_body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HA API {resp.status_code}: {resp.text[:800]}")
        if resp.status_code == 204 or not resp.content:
            return {"ok": True}
        if text:
            return resp.text
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            return resp.json()
        return resp.text


async def _ws_call(payload: dict, timeout: float = 20.0) -> Any:
    """Home Assistant WebSocket command (Lovelace has no REST API anymore)."""
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Home Assistant API unavailable (not running as HA add-on)")
    url = os.environ.get("HASSAI_HA_WS", "ws://supervisor/core/websocket")
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:
        from websockets import connect as ws_connect  # type: ignore

    async with ws_connect(url, open_timeout=8, close_timeout=4) as ws:
        hello = json.loads(await ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"unexpected HA websocket hello: {hello.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA websocket auth failed: {auth.get('message') or auth}")
        msg_id = 1
        await ws.send(json.dumps({"id": msg_id, **payload}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = await ws.recv()
            data = json.loads(raw)
            if data.get("type") in {"event", "pong"}:
                continue
            if data.get("id") != msg_id:
                continue
            if not data.get("success"):
                err = data.get("error") or {}
                code = err.get("code") or "error"
                message = err.get("message") or str(data)
                raise RuntimeError(f"HA websocket {code}: {message}")
            return data.get("result")
    raise RuntimeError("HA websocket timed out")


async def ping() -> tuple[bool, str]:
    """Return (ok, detail) for a cheap Core API check."""
    if not is_available():
        return False, "not running as HA add-on (no SUPERVISOR_TOKEN)"
    try:
        await _core("GET", "/config", timeout=8.0)
        return True, "ok"
    except Exception as e:
        log.warning("HA Core ping failed: %s", e)
        return False, str(e)


async def list_ha_people() -> list[dict]:
    """HA person entities (often linked to login users via user_id)."""
    if not is_available():
        return []
    try:
        states = await _core("GET", "/states")
    except Exception as e:
        log.warning("list_ha_people failed: %s", e)
        return []
    people = []
    if not isinstance(states, list):
        return people
    for st in states:
        eid = st.get("entity_id") or ""
        if not eid.startswith("person."):
            continue
        attrs = st.get("attributes") or {}
        people.append({
            "entity_id": eid,
            "name": attrs.get("friendly_name") or eid,
            "user_id": attrs.get("user_id") or "",
        })
    return people


async def _core(method: str, path: str, **kwargs) -> Any:
    return await _http(method, f"{_SUPERVISOR}/core/api{path}", **kwargs)


async def _core_query(path: str, params: dict[str, Any]) -> Any:
    clean: dict[str, Any] = {}
    for key, value in params.items():
        if value is None or value is False:
            continue
        if value is True or value == "":
            clean[key] = ""
        else:
            clean[key] = value
    qs = urlencode(clean, doseq=True)
    suffix = f"?{qs}" if qs else ""
    return await _core("GET", f"{path}{suffix}")


async def _supervisor(method: str, path: str, **kwargs) -> Any:
    return await _http(method, f"{_SUPERVISOR}{path}", **kwargs)


def _safe_config_path(rel: str) -> Path:
    raw = (rel or "").strip().lstrip("/")
    if not raw or raw.endswith("/"):
        raise ValueError("path is required (file, not directory)")
    target = (_HA_CONFIG / raw).resolve()
    root = _HA_CONFIG.resolve()
    if root not in target.parents and target != root:
        raise ValueError("path escapes /config")
    if target.suffix.lower() not in _ALLOWED_FILE_SUFFIXES and target.name not in (
        "configuration.yaml",
        "automations.yaml",
        "scripts.yaml",
        "scenes.yaml",
        "secrets.yaml",
    ):
        if "." not in target.name:
            raise ValueError("refusing path without a known text suffix")
        if target.suffix.lower() not in _ALLOWED_FILE_SUFFIXES:
            raise ValueError(f"refusing file type {target.suffix}")
    return target


# ── Tools ──────────────────────────────────────────

def build_ha_tools() -> list[dict]:
    if not is_available():
        return []
    return [_tool(name, spec) for name, spec in _TOOL_SPECS.items()]


def _tool(name: str, spec: dict) -> dict:
    return {"type": "function", "function": {"name": name, **spec}}


_TOOL_SPECS: dict[str, dict] = {
    "ha_list_entities": {
        "description": (
            "List Home Assistant entities (entity_id, name, state, domain). "
            "All domains included by default — use domain= or search= to narrow. "
            "Use offset= for pagination."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "e.g. light, switch, climate, update"},
                "search": {"type": "string", "description": "Substring on entity_id or friendly_name"},
                "state_filter": {"type": "string", "description": "Exact state value, e.g. on, off, unavailable"},
                "limit": {"type": "integer", "description": "Default 40, max 120"},
                "offset": {"type": "integer", "description": "Skip N matches for pagination"},
                "sort": {"type": "string", "enum": ["entity_id", "name", "state"], "description": "Sort order"},
                "include_all_domains": {
                    "type": "boolean",
                    "description": "Default true — list every domain, not only common ones",
                },
                "area_id": {"type": "string", "description": "Filter by entity registry area_id"},
                "area_name": {"type": "string", "description": "Substring match on area name"},
                "device_id": {"type": "string", "description": "Filter by device_id"},
                "include_disabled": {"type": "boolean", "description": "Include disabled registry entries"},
                "include_hidden": {"type": "boolean"},
                "include_registry": {
                    "type": "boolean",
                    "description": "Merge entity registry for area/device/name columns (default true)",
                },
            },
        },
    },
    "ha_get_state": {
        "description": (
            "Read one entity state and attributes. "
            "Use full_attributes for climate/media_player; include_capabilities for service hints."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "full_attributes": {"type": "boolean", "description": "Return all attributes (not capped)"},
                "include_timestamps": {"type": "boolean", "description": "Include last_changed / last_updated"},
                "include_capabilities": {"type": "boolean", "description": "Summarize controllable fields"},
            },
            "required": ["entity_id"],
        },
    },
    "ha_call_service": {
        "description": (
            "Call a Home Assistant service. Use ha_list_services to discover valid domain.service names. "
            "Pass entity_id here or entity_id: [list] inside data for multiple targets. "
            "Set verify=true to read state after the call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "service": {"type": "string"},
                "entity_id": {"type": "string", "description": "Single entity or omit and use data.entity_id list"},
                "data": {"type": "object"},
                "verify": {"type": "boolean", "description": "Run ha_get_state after a successful call"},
            },
            "required": ["domain", "service"],
        },
    },
    "ha_list_services": {
        "description": (
            "List available Home Assistant services and common fields. "
            "Pass domain=light (etc.) to narrow."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Optional domain filter"},
            },
        },
    },
    "ha_list_entity_registry": {
        "description": (
            "List entity registry entries (official names, areas, devices, disabled/hidden). "
            "Use before ha_update_entity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "search": {"type": "string"},
                "area_id": {"type": "string"},
                "include_disabled": {"type": "boolean"},
            },
        },
    },
    "ha_get_entity_registry": {
        "description": "Get one entity registry entry by entity_id.",
        "parameters": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    "ha_update_entity": {
        "description": (
            "Update entity registry metadata: rename, move to area, icon, disable/hide. "
            "Use ha_list_areas for area_id. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "name": {"type": "string", "description": "Display name"},
                "new_entity_id": {"type": "string", "description": "Rename entity_id"},
                "area_id": {"type": "string"},
                "area_name": {"type": "string", "description": "Resolve area by name"},
                "icon": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "disabled": {"type": "boolean", "description": "true=disable, false=enable"},
                "hidden": {"type": "boolean", "description": "true=hide, false=show"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "confirm"],
        },
    },
    "ha_list_areas": {
        "description": "List Home Assistant areas (rooms). Use area_id in ha_update_entity / filters.",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_create_area": {
        "description": "Create a Home Assistant area (room). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "icon": {"type": "string"},
                "floor_id": {"type": "string"},
                "floor_name": {"type": "string", "description": "Resolve floor via ha_list_floors"},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "label_id or name"},
                "confirm": {"type": "boolean"},
            },
            "required": ["name", "confirm"],
        },
    },
    "ha_update_area": {
        "description": "Update area metadata (rename, icon, labels, floor). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "area_id": {"type": "string"},
                "name": {"type": "string"},
                "icon": {"type": "string"},
                "floor_id": {"type": "string"},
                "floor_name": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "confirm": {"type": "boolean"},
            },
            "required": ["area_id", "confirm"],
        },
    },
    "ha_list_labels": {
        "description": "List Home Assistant labels (label_id, name). Use before assigning labels to entities/devices.",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_create_label": {
        "description": "Create a label. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "color": {"type": "string", "description": "Theme color or hex"},
                "icon": {"type": "string"},
                "description": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["name", "confirm"],
        },
    },
    "ha_update_label": {
        "description": "Update a label. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "label_id": {"type": "string"},
                "name": {"type": "string"},
                "color": {"type": "string"},
                "icon": {"type": "string"},
                "description": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["label_id", "confirm"],
        },
    },
    "ha_list_devices": {
        "description": "List Home Assistant devices with area, manufacturer, and model.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Substring on name/manufacturer/model"},
            },
        },
    },
    "ha_get_device": {
        "description": "Get one device and its entity_ids by device_id.",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
        },
    },
    "ha_update_device": {
        "description": (
            "Update device registry: rename, move to area, labels, disable. "
            "Moves all entities on the device when area changes. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "name_by_user": {"type": "string"},
                "area_id": {"type": "string"},
                "area_name": {"type": "string", "description": "Resolve area by name"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "disabled": {"type": "boolean", "description": "true=disable, false=enable"},
                "confirm": {"type": "boolean"},
            },
            "required": ["device_id", "confirm"],
        },
    },
    "ha_set_state": {
        "description": (
            "Set state/attributes on helper entities only (input_*, counter, timer, schedule). "
            "For lights/switches/climate use ha_call_service. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "state": {"type": "string"},
                "attributes": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "state", "confirm"],
        },
    },
    "ha_get_history": {
        "description": (
            "State change history for one or more entities (REST). "
            "Use after automations or to verify toggles. Pass entity_id or entity_ids."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "entity_ids": {"type": "array", "items": {"type": "string"}},
                "hours": {"type": "integer", "description": "Lookback window (default 24, max 168)"},
                "limit": {"type": "integer", "description": "Max state rows per entity (default 40)"},
                "significant_changes_only": {"type": "boolean"},
            },
        },
    },
    "ha_get_logbook": {
        "description": (
            "Logbook entries (who changed what). Optional entity_id filter. "
            "Good for tracing automations and user actions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "hours": {"type": "integer", "description": "Lookback window (default 24, max 168)"},
                "limit": {"type": "integer", "description": "Max rows (default 60)"},
            },
        },
    },
    "ha_get_entity_source": {
        "description": (
            "Which integration owns an entity (entity/source WebSocket). "
            "Requires entity_id, search, or domain — never call without a filter."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "domain": {"type": "string", "description": "Entity domain or source integration"},
                "search": {"type": "string", "description": "Substring on entity_id or source"},
            },
        },
    },
    "ha_list_exposed_entities": {
        "description": (
            "List entities exposed to voice assistants (Assist/Alexa/Google). "
            "Optional assistant=conversation filter."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "assistant": {
                    "type": "string",
                    "enum": ["conversation", "cloud.alexa", "cloud.google_assistant"],
                },
                "search": {"type": "string"},
            },
        },
    },
    "ha_expose_entity": {
        "description": (
            "Expose or hide entities for voice assistants. "
            "Default assistant is conversation (Assist). confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "entity_ids": {"type": "array", "items": {"type": "string"}},
                "should_expose": {"type": "boolean"},
                "assistants": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["conversation", "cloud.alexa", "cloud.google_assistant"],
                    },
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["should_expose", "confirm"],
        },
    },
    "ha_list_floors": {
        "description": "List Home Assistant floors (building levels). Use floor_id/floor_name in ha_create_area.",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_create_floor": {
        "description": "Create a floor level. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "level": {"type": "integer", "description": "Numeric level, e.g. 0=ground, 1=first"},
                "icon": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["name", "confirm"],
        },
    },
    "ha_update_floor": {
        "description": "Update floor metadata. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "floor_id": {"type": "string"},
                "name": {"type": "string"},
                "level": {"type": "integer"},
                "icon": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["floor_id", "confirm"],
        },
    },
    "ha_list_automations": {
        "description": "List automation.* entities with mode and last_triggered.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "state_filter": {"type": "string", "description": "on or off"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    },
    "ha_get_automation": {
        "description": "Get one automation entity state and attributes.",
        "parameters": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    "ha_trigger_automation": {
        "description": "Trigger an automation entity. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "skip_condition": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "confirm"],
        },
    },
    "ha_list_scripts": {
        "description": "List script.* entities.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    },
    "ha_run_script": {
        "description": "Run a script entity (script.turn_on). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "variables": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "confirm"],
        },
    },
    "ha_list_scenes": {
        "description": "List scene.* entities and entity counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    },
    "ha_activate_scene": {
        "description": "Activate a scene (scene.turn_on). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "confirm"],
        },
    },
    "ha_list_config_entries": {
        "description": "List Home Assistant integrations (config entries). Filter by domain or search.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Integration domain, e.g. mqtt, shelly"},
                "search": {"type": "string"},
            },
        },
    },
    "ha_get_config_entry": {
        "description": "Get one integration config entry by entry_id from ha_list_config_entries.",
        "parameters": {
            "type": "object",
            "properties": {"entry_id": {"type": "string"}},
            "required": ["entry_id"],
        },
    },
    "ha_reload_config_entry": {
        "description": "Reload an integration config entry. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entry_id", "confirm"],
        },
    },
    "ha_list_statistic_ids": {
        "description": "List long-term statistic ids (usually sensor.*). Use before ha_get_statistics.",
        "parameters": {
            "type": "object",
            "properties": {"search": {"type": "string"}},
        },
    },
    "ha_get_statistics": {
        "description": (
            "Long-term statistics for sensors (recorder). "
            "Pass statistic_id or entity_id; period hour/day/week/month."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "statistic_id": {"type": "string"},
                "statistic_ids": {"type": "array", "items": {"type": "string"}},
                "entity_id": {"type": "string", "description": "Alias for statistic_id when they match"},
                "hours": {"type": "integer", "description": "Lookback (default 24, max 720)"},
                "period": {
                    "type": "string",
                    "enum": ["5minute", "hour", "day", "week", "month"],
                    "description": "Default hour",
                },
            },
        },
    },
    "ha_list_groups": {
        "description": "List group.* entities and member counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    },
    "ha_list_zones": {
        "description": "List zone.* entities (geofences).",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    },
    "ha_list_persons": {
        "description": "List person.* entities linked to HA users and device trackers.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    },
    "ha_system_info": {
        "description": "HA Core + Supervisor + host summary (version, unhealthy, add-ons).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_get_logs": {
        "description": (
            "Read recent logs. source=core (HA error log), supervisor, or host. "
            "Use search to filter lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["core", "supervisor", "host"],
                    "description": "Default core",
                },
                "search": {"type": "string", "description": "Case-insensitive filter"},
                "lines": {"type": "integer", "description": "Last N lines (default 80, max 200)"},
            },
        },
    },
    "ha_list_problems": {
        "description": (
            "List Supervisor resolution issues/suggestions and a short Core error-log sample. "
            "Use this first when diagnosing HA problems."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_apply_fix": {
        "description": "Apply a Supervisor resolution suggestion by id from ha_list_problems.",
        "parameters": {
            "type": "object",
            "properties": {
                "suggestion_id": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Must be true to apply"},
            },
            "required": ["suggestion_id", "confirm"],
        },
    },
    "ha_check_config": {
        "description": "Run Home Assistant configuration check (same as Developer Tools → YAML check).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_reload": {
        "description": "Reload a HA YAML integration without full restart.",
        "parameters": {
            "type": "object",
            "properties": {
                "what": {
                    "type": "string",
                    "enum": [
                        "core", "automations", "scripts", "scenes", "template",
                        "themes", "groups", "input_boolean", "input_number",
                        "input_select", "input_text", "input_datetime", "persons",
                        "lovelace",
                    ],
                    "description": "What to reload. 'core' = homeassistant.reload_core_config",
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["what", "confirm"],
        },
    },
    "ha_list_dashboards": {
        "description": (
            "List Lovelace dashboards (url_path, title, mode: storage or yaml). "
            "Includes the default Overview dashboard (empty url_path)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_get_dashboard": {
        "description": (
            "Inspect a Lovelace dashboard. Returns a compact summary by default. "
            "Overview/default uses an empty url_path. "
            "Use view_path for a page/view (not the dashboard url_path). "
            "YAML dashboards: use ha_read_file / ha_write_file instead of save/upsert."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string", "description": "Dashboard url_path; empty = Overview/default"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer"},
                "view_path": {"type": "string", "description": "View page path (e.g. kitchen)"},
                "view_title": {"type": "string", "description": "Substring match on view title/path"},
                "include_cards": {"type": "boolean", "description": "List card summaries in the response"},
                "full": {"type": "boolean", "description": "Return raw JSON instead of summary (large)"},
                "force": {"type": "boolean", "description": "Force reload for YAML dashboards"},
            },
        },
    },
    "ha_create_dashboard": {
        "description": (
            "Create a new storage-mode Lovelace dashboard (sidebar entry). "
            "url_path must contain a hyphen (HA rule), e.g. energy-home. "
            "Optionally seeds one empty sections view."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string"},
                "title": {"type": "string"},
                "icon": {"type": "string", "description": "mdi:... icon"},
                "show_in_sidebar": {"type": "boolean"},
                "require_admin": {"type": "boolean"},
                "initial_view_title": {"type": "string", "description": "First view title (default Home)"},
                "confirm": {"type": "boolean"},
            },
            "required": ["url_path", "title", "confirm"],
        },
    },
    "ha_upsert_view": {
        "description": (
            "Add or replace a dashboard view/page (storage mode). "
            "Default view type is sections. Provide view object or title/path."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer", "description": "Replace this view index"},
                "view_path": {"type": "string", "description": "Replace view with this path, or set path on create"},
                "view_title": {"type": "string"},
                "title": {"type": "string"},
                "path": {"type": "string"},
                "view_type": {"type": "string", "description": "sections (default), masonry, panel, sidebar"},
                "icon": {"type": "string"},
                "view": {"type": "object", "description": "Full view JSON to insert/replace"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_upsert_section": {
        "description": "Add or replace a section on a sections-type view (storage mode).",
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer"},
                "view_path": {"type": "string"},
                "view_title": {"type": "string"},
                "section_index": {"type": "integer", "description": "Replace section; omit to append"},
                "title": {"type": "string", "description": "Optional heading card for a new section"},
                "section": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_save_dashboard": {
        "description": (
            "Save a full Lovelace dashboard config (storage mode only). "
            "Prefer ha_upsert_view / ha_upsert_card for small edits. "
            "Never pass truncated JSON from ha_get_dashboard."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string", "description": "Empty for default dashboard"},
                "config": {"type": "object", "description": "Full lovelace config JSON"},
                "confirm": {"type": "boolean"},
            },
            "required": ["config", "confirm"],
        },
    },
    "ha_upsert_card": {
        "description": (
            "Add or replace one card on a Lovelace view (storage mode). "
            "Sections views store cards under sections[].cards — use section_index. "
            "view_path selects the page/view; url_path selects the dashboard. "
            "If card_index is omitted, the card is appended."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string", "description": "Dashboard url_path; empty = Overview"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer"},
                "view_path": {"type": "string", "description": "View page path"},
                "view_title": {"type": "string"},
                "section_index": {"type": "integer", "description": "Sections view: target section"},
                "section_title": {"type": "string"},
                "create_section": {"type": "boolean", "description": "Create a section if needed"},
                "card_index": {"type": "integer", "description": "Replace this card; omit to append"},
                "card_path": {
                    "type": "string",
                    "description": "Optional dotted path for nested stack/grid cards (e.g. 2.1)",
                },
                "card": {"type": "object", "description": "Lovelace card JSON (must include type)"},
                "confirm": {"type": "boolean"},
            },
            "required": ["card", "confirm"],
        },
    },
    "ha_delete_card": {
        "description": "Delete one card from a Lovelace view or section (storage mode).",
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer"},
                "view_path": {"type": "string"},
                "view_title": {"type": "string"},
                "section_index": {"type": "integer"},
                "section_title": {"type": "string"},
                "card_index": {"type": "integer"},
                "card_path": {"type": "string", "description": "Nested stack/grid path (e.g. 2.1)"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_delete_view": {
        "description": (
            "Delete a view/page from a storage-mode dashboard. "
            "Cannot delete the last remaining view."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer"},
                "view_path": {"type": "string"},
                "view_title": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_update_dashboard": {
        "description": (
            "Update storage-mode dashboard metadata (title, icon, sidebar visibility). "
            "Uses dashboard_id from ha_list_dashboards (url_path/title also accepted)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dashboard_id": {
                    "type": "string",
                    "description": "Preferred id from ha_list_dashboards",
                },
                "url_path": {"type": "string", "description": "Alternative to dashboard_id"},
                "title": {"type": "string", "description": "New dashboard title"},
                "icon": {"type": "string"},
                "show_in_sidebar": {"type": "boolean"},
                "require_admin": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_delete_dashboard": {
        "description": (
            "Delete a storage-mode Lovelace dashboard (not Overview/default). "
            "Requires dashboard_id from ha_list_dashboards (url_path/title also accepted)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dashboard_id": {
                    "type": "string",
                    "description": "Preferred id from ha_list_dashboards",
                },
                "url_path": {"type": "string", "description": "Alternative to dashboard_id"},
                "title": {"type": "string", "description": "Find dashboard by title"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_list_lovelace_resources": {
        "description": "List Lovelace JS/CSS resources registered in Home Assistant.",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_append_card_yaml": {
        "description": (
            "Append a card to a YAML-mode dashboard (ui-lovelace.yaml or dashboards/*.yaml). "
            "Then ha_reload what=lovelace confirm=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_path": {"type": "string", "description": "Empty = Overview/ui-lovelace.yaml"},
                "dashboard_url": _DASHBOARD_URL,
                "view_index": {"type": "integer"},
                "view_path": {"type": "string"},
                "view_title": {"type": "string"},
                "section_index": {"type": "integer"},
                "section_title": {"type": "string"},
                "create_section": {"type": "boolean"},
                "card": {"type": "object", "description": "Lovelace card JSON (must include type)"},
                "confirm": {"type": "boolean"},
            },
            "required": ["card", "confirm"],
        },
    },
    "ha_list_files": {
        "description": "List text config files under /config (HA configuration directory).",
        "parameters": {
            "type": "object",
            "properties": {
                "subdir": {"type": "string", "description": "Relative folder, e.g. custom_components"},
                "search": {"type": "string"},
            },
        },
    },
    "ha_read_file": {
        "description": "Read a text file from /config (YAML/JSON). Example: configuration.yaml, automations.yaml, ui-lovelace.yaml.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative to /config"},
            },
            "required": ["path"],
        },
    },
    "ha_write_file": {
        "description": (
            "Write a text file under /config. Creates parent dirs. "
            "Always call ha_check_config after YAML edits. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["path", "content", "confirm"],
        },
    },
}

HA_TOOL_NAMES = set(_TOOL_SPECS)


def ha_system_hint(cfg: dict | None = None) -> str:
    if not is_available():
        return ""
    if cfg is None:
        try:
            from config import load_config
            cfg = load_config()
        except Exception:
            cfg = {}
    template = (cfg or {}).get("ha_agent_prompt")
    return et.render_ha_agent_prompt(template or "", sorted(HA_TOOL_NAMES))


# ── Dispatch ───────────────────────────────────────

async def run_ha_tool(name: str, args: dict) -> str:
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Error: unknown HA tool '{name}'"
    try:
        return await handler(args or {})
    except Exception as e:
        log.error("HA tool %s failed: %s", name, e)
        msg = str(e)
        hint = lt.dashboard_error_hint(name, msg)
        if hint:
            return f"Error: {msg}. {hint}"
        hint = et.entity_error_hint(name, msg)
        if hint:
            return f"Error: {msg}. {hint}"
        if ("404" in msg or "not_found" in msg.lower()) and name in {
            "ha_list_dashboards", "ha_get_dashboard", "ha_save_dashboard",
            "ha_create_dashboard", "ha_upsert_view", "ha_upsert_section",
            "ha_upsert_card", "ha_delete_card", "ha_delete_view",
            "ha_update_dashboard", "ha_delete_dashboard", "ha_append_card_yaml",
        }:
            return (
                f"Error: {msg}. "
                "If this dashboard is YAML mode, edit the YAML file with ha_read_file / ha_write_file instead."
            )
        return f"Error: {msg}"


def _require_confirm(args: dict) -> str | None:
    if args.get("confirm") is True:
        return None
    return "Refused: set confirm=true after the user explicitly agrees."


def _dash_args(args: dict) -> dict:
    return lt.resolve_dashboard_args(args or {})


async def _fetch_states_cached() -> list[dict]:
    now = time.time()
    cached = _STATES_CACHE.get("rows")
    if cached is not None and (now - float(_STATES_CACHE.get("ts") or 0)) < _STATES_CACHE_TTL:
        return cached
    states = await _core("GET", "/states")
    if not isinstance(states, list):
        raise RuntimeError("unexpected states payload")
    _STATES_CACHE["rows"] = states
    _STATES_CACHE["ts"] = now
    return states


async def _fetch_registry_bundle() -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    now = time.time()
    if (
        _REGISTRY_CACHE.get("entities") is not None
        and (now - float(_REGISTRY_CACHE.get("ts") or 0)) < _REGISTRY_CACHE_TTL
    ):
        return (
            _REGISTRY_CACHE["entities"],
            _REGISTRY_CACHE["areas"],
            _REGISTRY_CACHE["devices"],
            _REGISTRY_CACHE["labels"],
            _REGISTRY_CACHE["floors"],
        )
    entities = await _ws_call({"type": "config/entity_registry/list"})
    areas = await _ws_call({"type": "config/area_registry/list"})
    devices = await _ws_call({"type": "config/device_registry/list"})
    try:
        labels = await _ws_call({"type": "config/label_registry/list"})
    except Exception as e:
        log.warning("Label registry unavailable: %s", e)
        labels = []
    try:
        floors = await _ws_call({"type": "config/floor_registry/list"})
    except Exception as e:
        log.warning("Floor registry unavailable: %s", e)
        floors = []
    if not isinstance(entities, list):
        entities = []
    if not isinstance(areas, list):
        areas = []
    if not isinstance(devices, list):
        devices = []
    if not isinstance(labels, list):
        labels = []
    if not isinstance(floors, list):
        floors = []
    _REGISTRY_CACHE["entities"] = entities
    _REGISTRY_CACHE["areas"] = areas
    _REGISTRY_CACHE["devices"] = devices
    _REGISTRY_CACHE["labels"] = labels
    _REGISTRY_CACHE["floors"] = floors
    _REGISTRY_CACHE["ts"] = now
    return entities, areas, devices, labels, floors


def _invalidate_registry_cache() -> None:
    _REGISTRY_CACHE["ts"] = 0.0


async def _registry_indexes() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    entities, areas, devices, labels, *_ = await _fetch_registry_bundle()
    area_labels, area_names = et.index_areas(areas)
    device_labels, device_names = et.index_devices(devices)
    _label_labels, label_names = et.index_labels(labels)
    return area_labels, area_names, device_labels, device_names, label_names


async def _list_entities(args: dict) -> str:
    states = await _fetch_states_cached()
    use_registry = args.get("include_registry") is not False
    try:
        limit = int(args.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    try:
        offset = int(args.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0

    if use_registry and is_available():
        try:
            entities, areas, devices, _labels, *_ = await _fetch_registry_bundle()
            area_labels, area_names = et.index_areas(areas)
            device_labels, _device_names = et.index_devices(devices)
            merged = et.merge_entities(
                states,
                et.registry_by_entity_id(entities),
                area_labels,
                device_labels,
            )
            filtered = et.filter_enriched(merged, args)
            sorted_rows = et.sort_enriched(filtered, args.get("sort"))
            page, total = et.paginate_states(sorted_rows, limit, offset)
            return et.format_enriched_list(page, total=total, offset=offset, limit=limit)
        except Exception as e:
            log.warning("Registry merge failed, falling back to states-only list: %s", e)

    filtered = et.filter_states(states, args)
    sorted_rows = et.sort_states(filtered, args.get("sort"))
    page, total = et.paginate_states(sorted_rows, limit, offset)
    return et.format_entity_list(page, total=total, offset=offset, limit=limit)


async def _get_state(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    state = await _core("GET", f"/states/{entity_id}")
    return et.format_state_detail(state, args)


async def _call_service(args: dict) -> str:
    domain = (args.get("domain") or "").strip()
    service = (args.get("service") or "").strip()
    if not domain or not service:
        return "Error: domain and service are required"
    data = dict(args.get("data") or {})
    entity_id = (args.get("entity_id") or "").strip()
    if entity_id:
        data["entity_id"] = entity_id
    result = await _core("POST", f"/services/{domain}/{service}", json_body=data)
    target = entity_id or data.get("entity_id") or "(no entity_id)"
    lines = [f"OK: called {domain}.{service} on {target}"]
    if isinstance(result, list) and result:
        changed = [
            row.get("entity_id") for row in result if isinstance(row, dict) and row.get("entity_id")
        ]
        if changed:
            preview = ", ".join(changed[:8])
            if len(changed) > 8:
                preview += f", … (+{len(changed) - 8})"
            lines.append(f"changed: {preview}")
    elif isinstance(result, dict) and result:
        lines.append(_dump(result, max_chars=4000))
    verify_id = entity_id or (
        data.get("entity_id")[0]
        if isinstance(data.get("entity_id"), list) and data.get("entity_id")
        else (data.get("entity_id") if isinstance(data.get("entity_id"), str) else "")
    )
    if args.get("verify") and verify_id:
        lines.append("verify:")
        lines.append(await _get_state({"entity_id": verify_id, "include_capabilities": True}))
    return "\n".join(lines)


async def _list_services(args: dict) -> str:
    services = await _core("GET", "/services")
    domain = (args.get("domain") or "").strip().lower() or None
    return et.format_services_index(services, domain)


async def _list_entity_registry(args: dict) -> str:
    entities, areas, _devices, _labels, *_ = await _fetch_registry_bundle()
    area_labels, _area_names = et.index_areas(areas)
    filtered = et.filter_registry_entries(entities, args)
    return et.format_registry_list(filtered, area_labels)


async def _get_entity_registry(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    entities, areas, devices, _labels, *_ = await _fetch_registry_bundle()
    area_labels, _area_names = et.index_areas(areas)
    device_labels, _device_names = et.index_devices(devices)
    reg = et.registry_by_entity_id(entities).get(entity_id)
    if not reg:
        return f"Error: no registry entry for {entity_id}"
    body = et.format_registry_entry(reg, area_labels, device_labels)
    try:
        state = await _core("GET", f"/states/{entity_id}")
        body += "\n\nlive state:\n" + et.format_state_detail(state, {"include_capabilities": True})
    except Exception:
        pass
    return body


async def _update_entity(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    _entities, areas, _devices, labels, *_ = await _fetch_registry_bundle()
    _area_labels, area_names = et.index_areas(areas)
    _label_labels, label_names = et.index_labels(labels)
    changes = et.build_entity_update_payload(args, area_names, label_names)
    if not changes:
        return "Error: provide at least one of name, new_entity_id, area_id, area_name, icon, labels, disabled, hidden"
    payload: dict[str, Any] = {"type": "config/entity_registry/update", "entity_id": entity_id, **changes}
    result = await _ws_call(payload)
    new_id = entity_id
    if isinstance(result, dict) and result.get("entity_id"):
        new_id = str(result["entity_id"])
    elif changes.get("new_entity_id"):
        new_id = str(changes["new_entity_id"])
    _invalidate_registry_cache()
    return f"OK: updated entity registry entry {entity_id} → {new_id}"


async def _list_areas(_args: dict) -> str:
    _entities, areas, _devices, _labels, *_ = await _fetch_registry_bundle()
    return et.format_area_list(areas)


async def _create_area(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    _entities, _areas, _devices, labels, floors = await _fetch_registry_bundle()
    _label_labels, label_names = et.index_labels(labels)
    _floor_labels, floor_names = et.index_floors(floors)
    payload = et.build_area_create_payload(args, label_names, floor_names)
    if not payload.get("name"):
        return "Error: name is required"
    result = await _ws_call({"type": "config/area_registry/create", **payload})
    area_id = result.get("area_id") if isinstance(result, dict) else "?"
    _invalidate_registry_cache()
    return f"OK: created area {payload['name']} (area_id={area_id})"


async def _update_area(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    _entities, _areas, _devices, labels, floors = await _fetch_registry_bundle()
    _label_labels, label_names = et.index_labels(labels)
    _floor_labels, floor_names = et.index_floors(floors)
    payload = et.build_area_update_payload(args, label_names, floor_names)
    if not payload.get("area_id"):
        return "Error: area_id is required"
    if len(payload) <= 1:
        return "Error: provide at least one of name, icon, labels, floor_id, floor_name"
    area_id = payload.pop("area_id")
    result = await _ws_call({"type": "config/area_registry/update", "area_id": area_id, **payload})
    name = result.get("name") if isinstance(result, dict) else area_id
    _invalidate_registry_cache()
    return f"OK: updated area {name} (area_id={area_id})"


async def _list_labels(_args: dict) -> str:
    _entities, _areas, _devices, labels, *_ = await _fetch_registry_bundle()
    return et.format_label_list(labels)


async def _create_label(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    payload = et.build_label_create_payload(args)
    if not payload.get("name"):
        return "Error: name is required"
    result = await _ws_call({"type": "config/label_registry/create", **payload})
    label_id = result.get("label_id") if isinstance(result, dict) else "?"
    _invalidate_registry_cache()
    return f"OK: created label {payload['name']} (label_id={label_id})"


async def _update_label(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    payload = et.build_label_update_payload(args)
    if not payload.get("label_id"):
        return "Error: label_id is required"
    if len(payload) <= 1:
        return "Error: provide at least one of name, color, icon, description"
    label_id = payload.pop("label_id")
    result = await _ws_call({"type": "config/label_registry/update", "label_id": label_id, **payload})
    name = result.get("name") if isinstance(result, dict) else label_id
    _invalidate_registry_cache()
    return f"OK: updated label {name} (label_id={label_id})"


async def _list_devices(args: dict) -> str:
    _entities, areas, devices, _labels, *_ = await _fetch_registry_bundle()
    area_labels, _area_names = et.index_areas(areas)
    search = (args.get("search") or "").strip().lower()
    if search:
        devices = [
            row
            for row in devices
            if isinstance(row, dict)
            and search
            in " ".join(
                str(row.get(key) or "")
                for key in ("name", "name_by_user", "manufacturer", "model", "id")
            ).lower()
        ]
    return et.format_device_list(devices, area_labels)


async def _get_device(args: dict) -> str:
    device_id = (args.get("device_id") or "").strip()
    if not device_id:
        return "Error: device_id is required"
    entities, areas, devices, _labels, *_ = await _fetch_registry_bundle()
    area_labels, _area_names = et.index_areas(areas)
    device = next((row for row in devices if isinstance(row, dict) and row.get("id") == device_id), None)
    if not device:
        return f"Error: no device with id {device_id}"
    linked = [row for row in entities if isinstance(row, dict) and row.get("device_id") == device_id]
    return et.format_device_detail(device, area_labels, linked)


async def _update_device(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    _entities, areas, _devices, labels, *_ = await _fetch_registry_bundle()
    _area_labels, area_names = et.index_areas(areas)
    _label_labels, label_names = et.index_labels(labels)
    payload = et.build_device_update_payload(args, area_names, label_names)
    if not payload.get("device_id"):
        return "Error: device_id is required"
    if len(payload) <= 1:
        return "Error: provide at least one of name_by_user, area_id, area_name, labels, disabled"
    result = await _ws_call({"type": "config/device_registry/update", **payload})
    device_id = payload["device_id"]
    name = ""
    if isinstance(result, dict):
        name = str(result.get("name_by_user") or result.get("name") or "")
    _invalidate_registry_cache()
    suffix = f" ({name})" if name else ""
    return f"OK: updated device {device_id}{suffix}"


async def _set_state(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    state = args.get("state")
    if not entity_id:
        return "Error: entity_id is required"
    if state is None:
        return "Error: state is required"
    if not et.can_set_state(entity_id):
        return (
            f"Error: ha_set_state is not allowed for {et.domain_of(entity_id)} entities. "
            "Use ha_call_service instead."
        )
    body: dict[str, Any] = {"state": str(state)}
    attrs = args.get("attributes")
    if isinstance(attrs, dict) and attrs:
        body["attributes"] = attrs
    await _core("POST", f"/states/{entity_id}", json_body=body)
    _STATES_CACHE["ts"] = 0.0
    verify = await _get_state({"entity_id": entity_id, "include_timestamps": True})
    return f"OK: set state on {entity_id}\n{verify}"


async def _get_history(args: dict) -> str:
    entity_ids = et.parse_entity_id_args(args)
    if not entity_ids:
        return "Error: entity_id or entity_ids is required"
    hours = et.clamp_hours(args.get("hours"))
    try:
        limit = int(args.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    limit = max(5, min(limit, 120))
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    params: dict[str, Any] = {
        "filter_entity_id": ",".join(entity_ids),
        "end_time": end.isoformat(),
        "minimal_response": True,
        "no_attributes": True,
    }
    if args.get("significant_changes_only"):
        params["significant_changes_only"] = True
    payload = await _core_query(f"/history/period/{start.isoformat()}", params)
    return et.format_history_response(payload, entity_ids, max_rows=limit)


async def _get_logbook(args: dict) -> str:
    entity_id = str(args.get("entity_id") or "").strip()
    hours = et.clamp_hours(args.get("hours"))
    try:
        limit = int(args.get("limit") or 60)
    except (TypeError, ValueError):
        limit = 60
    limit = max(5, min(limit, 120))
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    days = max(1, (hours + 23) // 24)
    params: dict[str, Any] = {"period": days}
    if entity_id:
        params["entity"] = entity_id
    payload = await _core_query(f"/logbook/{start.isoformat()}", params)
    if not isinstance(payload, list):
        return "No logbook entries."
    return et.format_logbook_entries(payload, max_rows=limit)


async def _get_entity_source(args: dict) -> str:
    if not any(args.get(k) for k in ("entity_id", "search", "domain")):
        return "Error: pass entity_id, search, or domain to narrow (full source list is too large)"
    result = await _ws_call({"type": "entity/source"})
    if not isinstance(result, dict):
        return "No entity sources."
    rows = et.filter_entity_sources(result, args)
    return et.format_entity_source_list(rows)


async def _list_exposed_entities(args: dict) -> str:
    result = await _ws_call({"type": "homeassistant/expose_entity/list"})
    exposed: dict[str, Any] = {}
    if isinstance(result, dict):
        raw = result.get("exposed_entities")
        exposed = raw if isinstance(raw, dict) else result
    if not isinstance(exposed, dict):
        exposed = {}
    rows = et.filter_exposed_entities(exposed, args)
    return et.format_exposed_entity_list(rows)


async def _expose_entity(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    payload = et.build_expose_entity_payload(args)
    if not payload:
        return "Error: entity_id/entity_ids and should_expose are required"
    await _ws_call({"type": "homeassistant/expose_entity", **payload})
    action = "exposed" if payload["should_expose"] else "hidden"
    preview = ", ".join(payload["entity_ids"][:6])
    if len(payload["entity_ids"]) > 6:
        preview += f", … (+{len(payload['entity_ids']) - 6})"
    assistants = ", ".join(payload["assistants"])
    return f"OK: {action} {preview} for {assistants}"


async def _list_domain_states(args: dict, domain: str, formatter) -> str:
    states = await _fetch_states_cached()
    query = dict(args or {})
    query["domain"] = domain
    filtered = et.filter_states(states, query)
    sorted_rows = et.sort_states(filtered, args.get("sort"))
    try:
        limit = int(args.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    try:
        offset = int(args.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    page, total = et.paginate_states(sorted_rows, limit, offset)
    return formatter(page, total=total, offset=offset, limit=limit)


async def _list_floors(_args: dict) -> str:
    _entities, _areas, _devices, _labels, floors = await _fetch_registry_bundle()
    return et.format_floor_list(floors)


async def _create_floor(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    payload = et.build_floor_create_payload(args)
    if not payload.get("name"):
        return "Error: name is required"
    result = await _ws_call({"type": "config/floor_registry/create", **payload})
    floor_id = result.get("floor_id") if isinstance(result, dict) else "?"
    _invalidate_registry_cache()
    return f"OK: created floor {payload['name']} (floor_id={floor_id})"


async def _update_floor(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    payload = et.build_floor_update_payload(args)
    if not payload.get("floor_id"):
        return "Error: floor_id is required"
    if len(payload) <= 1:
        return "Error: provide at least one of name, level, icon"
    floor_id = payload.pop("floor_id")
    result = await _ws_call({"type": "config/floor_registry/update", "floor_id": floor_id, **payload})
    name = result.get("name") if isinstance(result, dict) else floor_id
    _invalidate_registry_cache()
    return f"OK: updated floor {name} (floor_id={floor_id})"


async def _list_automations(args: dict) -> str:
    return await _list_domain_states(args, "automation", et.format_automation_list)


async def _get_automation(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    if not entity_id.startswith("automation."):
        return "Error: entity_id must be an automation.* entity"
    state = await _core("GET", f"/states/{entity_id}")
    return et.format_automation_detail(state)


async def _trigger_automation(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    data: dict[str, Any] = {"entity_id": entity_id}
    if args.get("skip_condition") is True:
        data["skip_condition"] = True
    await _core("POST", "/services/automation/trigger", json_body=data)
    return f"OK: triggered {entity_id}"


async def _list_scripts(args: dict) -> str:
    return await _list_domain_states(args, "script", et.format_script_list)


async def _run_script(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    data: dict[str, Any] = {"entity_id": entity_id}
    variables = args.get("variables")
    if isinstance(variables, dict) and variables:
        data.update(variables)
    await _core("POST", "/services/script/turn_on", json_body=data)
    return f"OK: ran script {entity_id}"


async def _list_scenes(args: dict) -> str:
    return await _list_domain_states(args, "scene", et.format_scene_list)


async def _activate_scene(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    await _core("POST", "/services/scene/turn_on", json_body={"entity_id": entity_id})
    return f"OK: activated scene {entity_id}"


async def _list_config_entries(args: dict) -> str:
    payload: dict[str, Any] = {"type": "config_entries/get"}
    domain = (args.get("domain") or "").strip()
    if domain:
        payload["domain"] = domain
    result = await _ws_call(payload)
    entries = et.filter_config_entries(et.normalize_config_entries(result), args)
    return et.format_config_entry_list(entries)


async def _get_config_entry(args: dict) -> str:
    entry_id = (args.get("entry_id") or "").strip()
    if not entry_id:
        return "Error: entry_id is required"
    result = await _ws_call({"type": "config_entries/get_single", "entry_id": entry_id})
    if not isinstance(result, dict):
        return f"Error: no config entry with id {entry_id}"
    return et.format_config_entry_detail(result)


async def _reload_config_entry(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entry_id = (args.get("entry_id") or "").strip()
    if not entry_id:
        return "Error: entry_id is required"
    await _core("POST", f"/config/config_entries/entry/{entry_id}/reload")
    return f"OK: reloaded config entry {entry_id}"


async def _list_statistic_ids(args: dict) -> str:
    result = await _ws_call({"type": "recorder/list_statistic_ids"})
    rows = result if isinstance(result, list) else []
    ids = et.filter_statistic_ids(rows, args)
    return et.format_statistic_id_list(ids)


async def _get_statistics(args: dict) -> str:
    ids: list[str] = []
    raw_ids = args.get("statistic_ids")
    if isinstance(raw_ids, list):
        ids.extend(str(item or "").strip() for item in raw_ids if str(item or "").strip())
    stat_id = (args.get("statistic_id") or args.get("entity_id") or "").strip()
    if stat_id:
        ids.append(stat_id)
    ids = ids[:5]
    if not ids:
        return "Error: statistic_id, statistic_ids, or entity_id is required"
    try:
        hours = int(args.get("hours") or 24)
    except (TypeError, ValueError):
        hours = 24
    hours = max(1, min(hours, 720))
    period = et.normalize_statistics_period(args.get("period"))
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    payload: dict[str, Any] = {
        "type": "recorder/statistics_during_period",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "statistic_ids": ids,
        "period": period,
    }
    result = await _ws_call(payload)
    try:
        limit = int(args.get("limit") or 24)
    except (TypeError, ValueError):
        limit = 24
    limit = max(3, min(limit, 60))
    return et.format_statistics_response(result, ids, max_rows=limit)


async def _list_groups(args: dict) -> str:
    return await _list_domain_states(args, "group", et.format_group_list)


async def _list_zones(args: dict) -> str:
    return await _list_domain_states(args, "zone", et.format_zone_list)


async def _list_persons(args: dict) -> str:
    return await _list_domain_states(args, "person", et.format_person_list)


async def _system_info(_args: dict) -> str:
    out: dict[str, Any] = {}
    try:
        out["core_config"] = await _core("GET", "/config")
    except Exception as e:
        out["core_config_error"] = str(e)
    for key, path in (
        ("supervisor", "/supervisor/info"),
        ("core", "/core/info"),
        ("host", "/host/info"),
        ("resolution", "/resolution/info"),
    ):
        try:
            out[key] = await _supervisor("GET", path)
        except Exception as e:
            out[f"{key}_error"] = str(e)
    # Shrink noisy blobs
    for k in ("supervisor", "core"):
        data = out.get(k)
        if isinstance(data, dict) and "data" in data:
            out[k] = data.get("data")
    return _dump(out)


async def _get_logs(args: dict) -> str:
    source = (args.get("source") or "core").strip().lower()
    search = (args.get("search") or "").strip().lower()
    try:
        lines_n = int(args.get("lines") or 80)
    except (TypeError, ValueError):
        lines_n = 80
    lines_n = max(10, min(lines_n, 200))

    if source == "core":
        try:
            text = await _core("GET", "/error_log", text=True, timeout=_LOG_TIMEOUT)
        except Exception:
            text = await _supervisor("GET", "/core/logs", text=True, timeout=_LOG_TIMEOUT)
    elif source == "supervisor":
        text = await _supervisor("GET", "/supervisor/logs", text=True, timeout=_LOG_TIMEOUT)
    elif source == "host":
        text = await _supervisor("GET", "/host/logs", text=True, timeout=_LOG_TIMEOUT)
    else:
        return "Error: source must be core, supervisor, or host"

    rows = str(text).splitlines()
    if search:
        rows = [ln for ln in rows if search in ln.lower()]
    rows = rows[-lines_n:]
    if not rows:
        return "No matching log lines."
    body = "\n".join(rows)
    if len(body) > 12_000:
        body = body[-12_000:]
    return body


async def _list_problems(_args: dict) -> str:
    payload: dict[str, Any] = {}
    try:
        payload["resolution"] = await _supervisor("GET", "/resolution/info")
    except Exception as e:
        payload["resolution_error"] = str(e)
    try:
        err = await _core("GET", "/error_log", text=True, timeout=_LOG_TIMEOUT)
        err_lines = [ln for ln in str(err).splitlines() if ln.strip()][-40:]
        payload["recent_core_errors"] = err_lines
    except Exception as e:
        payload["core_log_error"] = str(e)
    return _dump(payload)


async def _apply_fix(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    sid = (args.get("suggestion_id") or "").strip()
    if not sid:
        return "Error: suggestion_id is required"
    result = await _supervisor("POST", f"/resolution/suggestion/{sid}")
    return _dump(result)


async def _check_config(_args: dict) -> str:
    result = await _core("POST", "/config/core/check_config")
    return _dump(result)


_RELOAD_MAP = {
    "core": ("homeassistant", "reload_core_config"),
    "automations": ("automation", "reload"),
    "scripts": ("script", "reload"),
    "scenes": ("scene", "reload"),
    "template": ("template", "reload"),
    "themes": ("frontend", "reload_themes"),
    "groups": ("group", "reload"),
    "input_boolean": ("input_boolean", "reload"),
    "input_number": ("input_number", "reload"),
    "input_select": ("input_select", "reload"),
    "input_text": ("input_text", "reload"),
    "input_datetime": ("input_datetime", "reload"),
    "persons": ("person", "reload"),
    "lovelace": ("lovelace", "reload"),
}


async def _reload(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    what = (args.get("what") or "").strip()
    pair = _RELOAD_MAP.get(what)
    if not pair:
        return "Error: unknown reload target"
    domain, service = pair
    await _core("POST", f"/services/{domain}/{service}", json_body={})
    return f"OK: reloaded {what} ({domain}.{service})"


async def _dashboard_mode(url_path: str | None) -> str:
    ws_path = lt.ws_url_path(url_path)
    if ws_path is None:
        ui_lovelace = _HA_CONFIG / "ui-lovelace.yaml"
        if ui_lovelace.is_file():
            return "yaml"
        return "storage"
    rows = await _ws_call({"type": "lovelace/dashboards/list"})
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("url_path") == ws_path:
                return str(row.get("mode") or "storage")
    return "storage"


async def _list_dashboards(_args: dict) -> str:
    rows = await _ws_call({"type": "lovelace/dashboards/list"})
    dashboards: list[dict[str, Any]] = []
    if isinstance(rows, list):
        dashboards.extend(row for row in rows if isinstance(row, dict))

    overview_mode = await _dashboard_mode(None)
    overview: dict[str, Any] = {
        "title": "Overview",
        "url_path": "",
        "mode": overview_mode,
        "builtin": True,
    }
    if overview_mode == "yaml" and (_HA_CONFIG / "ui-lovelace.yaml").is_file():
        overview["config_file"] = "ui-lovelace.yaml"

    lines = ["Built-in dashboards:", lt.dump_json(overview, max_chars=2000)]
    enriched: list[dict[str, Any]] = []
    for row in dashboards:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if str(item.get("mode") or "") == "yaml":
            rel = lt.yaml_dashboard_file(item.get("url_path"))
            if rel:
                item["config_file"] = rel
        enriched.append(item)
    dashboards = enriched
    if dashboards:
        lines.append("")
        lines.append("Additional dashboards:")
        lines.append(lt.dump_json(dashboards, max_chars=10_000))
    else:
        lines.append("")
        lines.append("Additional dashboards: none")
    lines.append("")
    lines.append(
        "Notes: empty url_path = Overview/default. User 'pages' are views (view_path), not url_path. "
        "Each dashboard row includes id — use it for ha_update_dashboard / ha_delete_dashboard."
    )
    return "\n".join(lines)


async def _load_dashboard(url_path: str | None, *, force: bool = False) -> dict:
    mode = await _dashboard_mode(url_path)
    if mode == "yaml":
        raise RuntimeError(
            "dashboard is YAML mode; use ha_read_file / ha_write_file on ui-lovelace.yaml or dashboards/*.yaml"
        )
    payload: dict[str, Any] = {"type": "lovelace/config", "force": bool(force)}
    ws_path = lt.ws_url_path(url_path)
    if ws_path:
        payload["url_path"] = ws_path
    result = await _ws_call(payload)
    return lt.normalize_lovelace_config(result)


async def _save_dashboard_config(url_path: str | None, config: dict) -> None:
    mode = await _dashboard_mode(url_path)
    if mode == "yaml":
        raise RuntimeError(
            "dashboard is YAML mode; use ha_read_file / ha_write_file, then ha_reload what=lovelace"
        )
    payload: dict[str, Any] = {
        "type": "lovelace/config/save",
        "config": config,
    }
    ws_path = lt.ws_url_path(url_path)
    if ws_path:
        payload["url_path"] = ws_path
    await _ws_call(payload)


async def _get_dashboard(args: dict) -> str:
    args = _dash_args(args)
    url_path = args.get("url_path")
    mode = await _dashboard_mode(url_path)
    if mode == "yaml":
        ui = _HA_CONFIG / "ui-lovelace.yaml"
        if lt.ws_url_path(url_path) is None and ui.is_file():
            return await _read_file({"path": "ui-lovelace.yaml"})
        yaml_file = lt.yaml_dashboard_file(url_path)
        return (
            f"Error: dashboard is YAML mode. "
            f"Use ha_read_file on {yaml_file or 'ui-lovelace.yaml or dashboards/*.yaml'}."
        )

    cfg = await _load_dashboard(url_path, force=bool(args.get("force")))
    if args.get("full") is True:
        if args.get("view_index") is not None or args.get("view_title") or args.get("view_path"):
            idx, view = lt.pick_view(cfg, args)
            return lt.dump_json(
                {"url_path": url_path or "(default)", "view_index": idx, "view": view},
                max_chars=40_000,
            )
        return lt.dump_json({"url_path": url_path or "(default)", "config": cfg}, max_chars=40_000)

    if args.get("view_index") is not None or args.get("view_title") or args.get("view_path"):
        idx, view = lt.pick_view(cfg, args)
        include_cards = bool(args.get("include_cards"))
        body = lt.summarize_view(view, idx, include_cards=include_cards)
        label = lt._view_path(view, idx)
        dash = lt.ws_url_path(url_path)
        open_hint = f"/lovelace/{label}" if dash is None else f"/dashboard-{dash}/{label}"
        return (
            f"dashboard: {url_path or '(default)'}\n"
            f"mode: {mode}\n"
            f"{body}\n"
            f"open: {open_hint}"
        )

    return lt.summarize_dashboard(
        url_path,
        cfg,
        mode=mode,
        include_cards=bool(args.get("include_cards")),
    )


async def _create_dashboard(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    url_path = lt.ws_url_path(args.get("url_path"))
    title = (args.get("title") or "").strip()
    if not url_path:
        return "Error: url_path is required"
    if not title:
        return "Error: title is required"
    if "-" not in url_path:
        return "Error: url_path must contain a hyphen (Home Assistant rule), e.g. energy-home"

    payload: dict[str, Any] = {
        "type": "lovelace/dashboards/create",
        "url_path": url_path,
        "title": title,
    }
    if args.get("icon"):
        payload["icon"] = args["icon"]
    if args.get("show_in_sidebar") is not None:
        payload["show_in_sidebar"] = bool(args["show_in_sidebar"])
    if args.get("require_admin") is not None:
        payload["require_admin"] = bool(args["require_admin"])

    result = await _ws_call(payload)
    initial_title = (args.get("initial_view_title") or "Home").strip() or "Home"
    seed = {
        "views": [
            {
                "title": initial_title,
                "path": "home",
                "type": "sections",
                "sections": [{"type": "grid", "cards": []}],
            }
        ]
    }
    await _save_dashboard_config(url_path, seed)
    dash_id = (result or {}).get("id") if isinstance(result, dict) else "?"
    return (
        f"OK: created dashboard '{title}' url_path={url_path} id={dash_id}. "
        f"Open /dashboard-{url_path}/home — use ha_upsert_card with view_path=home."
    )


async def _upsert_view(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    args = _dash_args(args)
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    idx, view, action = lt.upsert_view_in_config(cfg, args)
    await _save_dashboard_config(url_path, cfg)
    path = lt._view_path(view, idx)
    dash = lt.ws_url_path(url_path)
    open_hint = f"/lovelace/{path}" if dash is None else f"/dashboard-{dash}/{path}"
    return f"OK: {action} ({lt._view_label(view, idx)}). Open {open_hint}"


async def _upsert_section(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    args = _dash_args(args)
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    vidx, view = lt.pick_view(cfg, args)
    sidx, _section, action = lt.upsert_section_in_view(view, args)
    cfg["views"][vidx] = view
    await _save_dashboard_config(url_path, cfg)
    return f"OK: {action} on view {vidx} ({lt._view_label(view, vidx)}) section {sidx}"


async def _save_dashboard(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    config = args.get("config")
    if not isinstance(config, dict) or "views" not in config:
        return "Error: config must be an object with a views array"
    url_path = args.get("url_path")
    await _save_dashboard_config(url_path, config)
    nviews = len(config.get("views") or [])
    return f"OK: saved dashboard {url_path or '(default)'} ({nviews} views)"


async def _upsert_card(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    args = _dash_args(args)
    card = args.get("card")
    if not isinstance(card, dict) or not card.get("type"):
        return "Error: card must be an object with type"
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    vidx, view = lt.pick_view(cfg, args)
    action, _removed = lt.mutate_card_in_view(
        view,
        args,
        card=card,
        create_section=bool(args.get("create_section")),
    )
    cfg["views"][vidx] = view
    await _save_dashboard_config(url_path, cfg)

    where = f"view {vidx} ({lt._view_label(view, vidx)})"
    verify = lt.summarize_view(view, vidx, include_cards=True)
    dash = lt.ws_url_path(url_path)
    path = lt._view_path(view, vidx)
    open_hint = f"/lovelace/{path}" if dash is None else f"/dashboard-{dash}/{path}"
    return f"OK: {action} on {where}\nopen: {open_hint}\n{verify}"


async def _delete_card(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    args = _dash_args(args)
    if args.get("card_index") is None and not (args.get("card_path") or "").strip():
        return "Error: card_index or card_path is required"
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    vidx, view = lt.pick_view(cfg, args)
    action, _removed = lt.mutate_card_in_view(view, args, delete=True)
    cfg["views"][vidx] = view
    await _save_dashboard_config(url_path, cfg)
    where = f"view {vidx} ({lt._view_label(view, vidx)})"
    return f"OK: {action} from {where}"


async def _delete_view(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    args = _dash_args(args)
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    idx, view, action = lt.delete_view_in_config(cfg, args)
    await _save_dashboard_config(url_path, cfg)
    dash = lt.ws_url_path(url_path)
    path = lt._view_path(view, idx)
    open_hint = f"/lovelace/{path}" if dash is None else f"/dashboard-{dash}/{path}"
    return f"OK: {action}. Was open at {open_hint}"


async def _find_dashboard(args: dict) -> dict:
    rows = await _ws_call({"type": "lovelace/dashboards/list"})
    if not isinstance(rows, list):
        raise RuntimeError("unexpected dashboards list payload")
    return lt.match_dashboard(rows, args)


async def _update_dashboard(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    lookup = {
        key: args[key]
        for key in ("dashboard_id", "url_path")
        if args.get(key) not in (None, "")
    }
    if not lookup:
        return "Error: provide dashboard_id or url_path (from ha_list_dashboards)"
    row = await _find_dashboard(lookup)
    dashboard_id = row.get("id")
    if not dashboard_id:
        return "Error: matched dashboard has no id"
    if str(row.get("mode") or "") == "yaml":
        return "Error: YAML dashboards cannot be updated with this tool"
    payload: dict[str, Any] = {
        "type": "lovelace/dashboards/update",
        "dashboard_id": dashboard_id,
    }
    changed = False
    for key in ("title", "icon", "show_in_sidebar", "require_admin"):
        if args.get(key) is not None:
            payload[key] = args[key]
            changed = True
    if not changed:
        return "Error: provide at least one of title, icon, show_in_sidebar, require_admin"
    await _ws_call(payload)
    url_path = row.get("url_path") or "?"
    return f"OK: updated dashboard {url_path} (id={dashboard_id})"


async def _delete_dashboard(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    row = await _find_dashboard(args)
    dashboard_id = row.get("id")
    if not dashboard_id:
        return "Error: matched dashboard has no id"
    if str(row.get("mode") or "") == "yaml":
        return "Error: YAML dashboards cannot be deleted with this tool"
    url_path = row.get("url_path") or "?"
    await _ws_call({"type": "lovelace/dashboards/delete", "dashboard_id": dashboard_id})
    return f"OK: deleted dashboard {url_path} (id={dashboard_id})"


async def _list_lovelace_resources(_args: dict) -> str:
    rows = await _ws_call({"type": "lovelace/resources/list"})
    if not isinstance(rows, list) or not rows:
        return "No Lovelace resources."
    return lt.dump_json(rows, max_chars=12_000)


async def _append_card_yaml(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    args = _dash_args(args)
    card = args.get("card")
    if not isinstance(card, dict) or not card.get("type"):
        return "Error: card must be an object with type"
    url_path = args.get("url_path")
    rel = lt.yaml_dashboard_file(url_path)
    if not rel:
        return "Error: could not resolve YAML file path"
    path = _safe_config_path(rel)
    if not path.is_file():
        return f"Error: not found: {rel}"
    text = path.read_text(encoding="utf-8", errors="replace")
    data = yaml.safe_load(text)
    updated, action = lt.append_card_to_yaml(data, args, card)
    new_text = yaml.safe_dump(
        updated,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    path.write_text(new_text, encoding="utf-8")
    dash = lt.ws_url_path(url_path)
    vpath = (args.get("view_path") or "home").strip() or "home"
    open_hint = f"/lovelace/{vpath}" if dash is None else f"/dashboard-{dash}/{vpath}"
    return (
        f"OK: {action} in {rel}\n"
        f"open: {open_hint}\n"
        "Run ha_reload what=lovelace confirm=true."
    )


async def _list_files(args: dict) -> str:
    if not _HA_CONFIG.is_dir():
        return "Error: /config is not mounted (add-on needs homeassistant_config:rw)"
    sub = (args.get("subdir") or "").strip().lstrip("/")
    search = (args.get("search") or "").strip().lower()
    base = (_HA_CONFIG / sub).resolve() if sub else _HA_CONFIG.resolve()
    if _HA_CONFIG.resolve() not in base.parents and base != _HA_CONFIG.resolve():
        return "Error: subdir escapes /config"
    if not base.is_dir():
        return f"Error: not a directory: {sub or '/'}"

    rows: list[str] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(_HA_CONFIG).as_posix()
        if p.suffix.lower() not in _ALLOWED_FILE_SUFFIXES and p.name not in {
            "configuration.yaml", "automations.yaml", "scripts.yaml", "scenes.yaml",
        }:
            continue
        if search and search not in rel.lower():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        rows.append(f"{rel}\t{size}")
        if len(rows) >= 120:
            rows.append("… truncated")
            break
    if not rows:
        return "No matching files."
    return "path\tsize\n" + "\n".join(rows)


async def _read_file(args: dict) -> str:
    path = _safe_config_path(args.get("path") or "")
    if not path.is_file():
        return f"Error: not found: {path.relative_to(_HA_CONFIG)}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > 80_000:
        return text[:80_000] + f"\n… truncated ({len(text)} chars)"
    return text


async def _write_file(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    path = _safe_config_path(args.get("path") or "")
    content = args.get("content")
    if not isinstance(content, str):
        return "Error: content must be a string"
    if len(content) > 400_000:
        return "Error: content too large (max 400KB)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    rel = path.relative_to(_HA_CONFIG).as_posix()
    hint = "Run ha_check_config for YAML."
    if rel == "ui-lovelace.yaml" or rel.startswith("dashboards/"):
        hint += " Then ha_reload what=lovelace confirm=true."
    return f"OK: wrote {rel} ({len(content)} chars). {hint}"


_HANDLERS: dict[str, Callable[[dict], Awaitable[str]]] = {
    "ha_list_entities": _list_entities,
    "ha_get_state": _get_state,
    "ha_call_service": _call_service,
    "ha_list_services": _list_services,
    "ha_list_entity_registry": _list_entity_registry,
    "ha_get_entity_registry": _get_entity_registry,
    "ha_update_entity": _update_entity,
    "ha_list_areas": _list_areas,
    "ha_create_area": _create_area,
    "ha_update_area": _update_area,
    "ha_list_labels": _list_labels,
    "ha_create_label": _create_label,
    "ha_update_label": _update_label,
    "ha_list_devices": _list_devices,
    "ha_get_device": _get_device,
    "ha_update_device": _update_device,
    "ha_set_state": _set_state,
    "ha_get_history": _get_history,
    "ha_get_logbook": _get_logbook,
    "ha_get_entity_source": _get_entity_source,
    "ha_list_exposed_entities": _list_exposed_entities,
    "ha_expose_entity": _expose_entity,
    "ha_list_floors": _list_floors,
    "ha_create_floor": _create_floor,
    "ha_update_floor": _update_floor,
    "ha_list_automations": _list_automations,
    "ha_get_automation": _get_automation,
    "ha_trigger_automation": _trigger_automation,
    "ha_list_scripts": _list_scripts,
    "ha_run_script": _run_script,
    "ha_list_scenes": _list_scenes,
    "ha_activate_scene": _activate_scene,
    "ha_list_config_entries": _list_config_entries,
    "ha_get_config_entry": _get_config_entry,
    "ha_reload_config_entry": _reload_config_entry,
    "ha_list_statistic_ids": _list_statistic_ids,
    "ha_get_statistics": _get_statistics,
    "ha_list_groups": _list_groups,
    "ha_list_zones": _list_zones,
    "ha_list_persons": _list_persons,
    "ha_system_info": _system_info,
    "ha_get_logs": _get_logs,
    "ha_list_problems": _list_problems,
    "ha_apply_fix": _apply_fix,
    "ha_check_config": _check_config,
    "ha_reload": _reload,
    "ha_list_dashboards": _list_dashboards,
    "ha_get_dashboard": _get_dashboard,
    "ha_create_dashboard": _create_dashboard,
    "ha_upsert_view": _upsert_view,
    "ha_upsert_section": _upsert_section,
    "ha_save_dashboard": _save_dashboard,
    "ha_upsert_card": _upsert_card,
    "ha_delete_card": _delete_card,
    "ha_delete_view": _delete_view,
    "ha_update_dashboard": _update_dashboard,
    "ha_delete_dashboard": _delete_dashboard,
    "ha_list_lovelace_resources": _list_lovelace_resources,
    "ha_append_card_yaml": _append_card_yaml,
    "ha_list_files": _list_files,
    "ha_read_file": _read_file,
    "ha_write_file": _write_file,
}
