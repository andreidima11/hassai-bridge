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
from pathlib import Path
from typing import Any, Callable, Awaitable

import httpx

from . import lovelace_tools as lt

log = logging.getLogger("hassai.ha")

_SUPERVISOR = "http://supervisor"
_TIMEOUT = 45.0
_LOG_TIMEOUT = 60.0
_MAX_JSON = 14_000
_HA_CONFIG = Path("/config")
_ALLOWED_FILE_SUFFIXES = {".yaml", ".yml", ".json", ".txt", ".log", ".conf", ".cfg"}

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
        "description": "List Home Assistant entities (id, name, state). Filter by domain and/or search.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "e.g. light, switch, climate, automation"},
                "search": {"type": "string", "description": "Substring on entity_id or friendly_name"},
                "limit": {"type": "integer", "description": "Default 40, max 80"},
            },
        },
    },
    "ha_get_state": {
        "description": "Full state + attributes for one entity.",
        "parameters": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    "ha_call_service": {
        "description": "Call a Home Assistant service (control devices, reload, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "service": {"type": "string"},
                "entity_id": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["domain", "service"],
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
                "view_index": {"type": "integer"},
                "view_path": {"type": "string", "description": "View page path"},
                "view_title": {"type": "string"},
                "section_index": {"type": "integer", "description": "Sections view: target section"},
                "section_title": {"type": "string"},
                "create_section": {"type": "boolean", "description": "Create a section if needed"},
                "card_index": {"type": "integer", "description": "Replace this card; omit to append"},
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
                "view_index": {"type": "integer"},
                "view_path": {"type": "string"},
                "view_title": {"type": "string"},
                "section_index": {"type": "integer"},
                "section_title": {"type": "string"},
                "card_index": {"type": "integer"},
                "confirm": {"type": "boolean"},
            },
            "required": ["card_index", "confirm"],
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


def ha_system_hint() -> str:
    if not is_available():
        return ""
    names = ", ".join(sorted(HA_TOOL_NAMES))
    return (
        "You are the Home Assistant administrator copilot. Tools: "
        f"{names}. "
        "Chain tools in one turn until the job is done — do not stop after a single lookup. "
        "Diagnose with ha_list_problems + ha_get_logs. "
        "Dashboards (WebSocket, storage mode): ha_list_dashboards → ha_get_dashboard (summary) → "
        "ha_create_dashboard / ha_upsert_view / ha_upsert_section / ha_upsert_card / ha_delete_card. "
        "Overview/default dashboard uses an empty url_path. A user 'page' is a view (view_path), not url_path. "
        "Sections views store cards in sections[].cards — pass section_index or create_section=true. "
        "YAML dashboards: ha_read_file / ha_write_file, then ha_reload what=lovelace confirm=true. "
        "Avoid ha_save_dashboard unless replacing the entire config from a trusted source. "
        "YAML / configuration.yaml: ha_read_file / ha_write_file then ha_check_config, then ha_reload if needed. "
        "Mutating tools need confirm=true: set it when the user already asked you to make the change. "
        "Do not wait for a second confirmation. "
        "After YAML writes, reload or tell the user to restart if check_config requires it."
    )


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
        if ("404" in msg or "not_found" in msg.lower()) and name in {
            "ha_list_dashboards", "ha_get_dashboard", "ha_save_dashboard",
            "ha_create_dashboard", "ha_upsert_view", "ha_upsert_section",
            "ha_upsert_card", "ha_delete_card",
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


async def _list_entities(args: dict) -> str:
    domain = (args.get("domain") or "").strip().lower()
    search = (args.get("search") or "").strip().lower()
    try:
        limit = int(args.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    limit = max(1, min(limit, 80))

    states = await _core("GET", "/states")
    if not isinstance(states, list):
        return "Error: unexpected states payload"

    rows: list[str] = []
    for st in states:
        eid = st.get("entity_id") or ""
        if domain and not eid.startswith(domain + "."):
            continue
        if not domain and not search:
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
    return "entity_id|name|state|area\n" + "\n".join(rows)


async def _get_state(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    state = await _core("GET", f"/states/{entity_id}")
    eid = state.get("entity_id", "?")
    attrs = state.get("attributes") or {}
    name = attrs.get("friendly_name") or eid
    lines = [f"entity_id: {eid}", f"name: {name}", f"state: {state.get('state')}"]
    skip = {"friendly_name", "supported_features", "attribution"}
    interesting = {k: v for k, v in attrs.items() if k not in skip}
    if interesting:
        items = list(interesting.items())[:24]
        lines.append("attributes: " + ", ".join(f"{k}={v!r}" for k, v in items))
    return "\n".join(lines)


async def _call_service(args: dict) -> str:
    domain = (args.get("domain") or "").strip()
    service = (args.get("service") or "").strip()
    if not domain or not service:
        return "Error: domain and service are required"
    data = dict(args.get("data") or {})
    entity_id = (args.get("entity_id") or "").strip()
    if entity_id:
        data["entity_id"] = entity_id
    await _core("POST", f"/services/{domain}/{service}", json_body=data)
    target = entity_id or data.get("entity_id") or "(no entity_id)"
    return f"OK: called {domain}.{service} on {target}"


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
    if dashboards:
        lines.append("")
        lines.append("Additional dashboards:")
        lines.append(lt.dump_json(dashboards, max_chars=10_000))
    else:
        lines.append("")
        lines.append("Additional dashboards: none")
    lines.append("")
    lines.append("Notes: empty url_path = Overview/default. User 'pages' are views (view_path), not url_path.")
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
    url_path = args.get("url_path")
    mode = await _dashboard_mode(url_path)
    if mode == "yaml":
        ui = _HA_CONFIG / "ui-lovelace.yaml"
        if lt.ws_url_path(url_path) is None and ui.is_file():
            return await _read_file({"path": "ui-lovelace.yaml"})
        return (
            "Error: dashboard is YAML mode. "
            "Use ha_read_file on ui-lovelace.yaml or dashboards/<name>.yaml."
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
    card = args.get("card")
    if not isinstance(card, dict) or not card.get("type"):
        return "Error: card must be an object with type"
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    vidx, view = lt.pick_view(cfg, args)
    container = lt.card_container(view, args, create_section=bool(args.get("create_section")))
    cards = list(container.cards)
    if args.get("card_index") is None:
        cards.append(card)
        action = f"appended card #{len(cards)-1}"
    else:
        cidx = int(args["card_index"])
        if cidx < 0 or cidx >= len(cards):
            return f"Error: card_index {cidx} out of range 0..{len(cards)-1}"
        cards[cidx] = card
        action = f"replaced card #{cidx}"
    container.write_back(cards)
    cfg["views"][vidx] = view
    await _save_dashboard_config(url_path, cfg)

    where = f"view {vidx} ({lt._view_label(view, vidx)})"
    if container.kind == "sections":
        where += f" section {container.section_index}"
    verify = lt.summarize_view(view, vidx, include_cards=True)
    return f"OK: {action} on {where}\n{verify}"


async def _delete_card(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    url_path = args.get("url_path")
    cfg = await _load_dashboard(url_path)
    vidx, view = lt.pick_view(cfg, args)
    container = lt.card_container(view, args)
    cards = list(container.cards)
    cidx = int(args.get("card_index"))
    if cidx < 0 or cidx >= len(cards):
        return f"Error: card_index {cidx} out of range 0..{len(cards)-1}"
    removed = cards.pop(cidx)
    container.write_back(cards)
    cfg["views"][vidx] = view
    await _save_dashboard_config(url_path, cfg)
    rtype = (removed or {}).get("type", "?")
    where = f"view {vidx} ({lt._view_label(view, vidx)})"
    if container.kind == "sections":
        where += f" section {container.section_index}"
    return f"OK: deleted card #{cidx} (type={rtype}) from {where}"


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
    return f"OK: wrote {rel} ({len(content)} chars). Run ha_check_config for YAML."


_HANDLERS: dict[str, Callable[[dict], Awaitable[str]]] = {
    "ha_list_entities": _list_entities,
    "ha_get_state": _get_state,
    "ha_call_service": _call_service,
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
    "ha_list_files": _list_files,
    "ha_read_file": _read_file,
    "ha_write_file": _write_file,
}
