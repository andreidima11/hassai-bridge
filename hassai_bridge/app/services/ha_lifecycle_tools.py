"""Extra Home Assistant domain tools: calendar, todo, helpers, traces, notify,
integrations admin, media players, Matter/Thread/BT, scenes CRUD, recorder, HACS.

Merged into homeassistant.build_ha_tools / run_ha_tool like supervisor_admin_tools.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

log = logging.getLogger("hassai.ha.lifecycle")

HELPER_DOMAINS = (
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
)

TOOL_SPECS: dict[str, dict] = {
    # ── Calendar ──────────────────────────────────────────
    "ha_list_calendars": {
        "description": "List calendar entities (name + entity_id).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_list_calendar_events": {
        "description": (
            "List events on a calendar between start and end (ISO date or datetime). "
            "Defaults: start=today, end=+7 days."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "start": {"type": "string", "description": "ISO start (date or datetime)"},
                "end": {"type": "string", "description": "ISO end (date or datetime)"},
            },
            "required": ["entity_id"],
        },
    },
    "ha_create_calendar_event": {
        "description": (
            "Create a calendar event. event needs summary, start, end "
            "(both date YYYY-MM-DD or both datetime ISO). Optional description, location, rrule. "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "event": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "event", "confirm"],
        },
    },
    "ha_update_calendar_event": {
        "description": "Update a calendar event by uid. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "uid": {"type": "string"},
                "event": {"type": "object"},
                "recurrence_id": {"type": "string"},
                "recurrence_range": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "uid", "event", "confirm"],
        },
    },
    "ha_delete_calendar_event": {
        "description": "Delete a calendar event by uid. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "uid": {"type": "string"},
                "recurrence_id": {"type": "string"},
                "recurrence_range": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "uid", "confirm"],
        },
    },
    # ── Todo / shopping ───────────────────────────────────
    "ha_list_todo_lists": {
        "description": (
            "List todo.* list entities with config_entry_id (needed to delete a whole list). "
            "Local lists use domain local_todo."
        ),
        "parameters": {
            "type": "object",
            "properties": {"search": {"type": "string"}},
        },
    },
    "ha_list_todo_items": {
        "description": "List items on a todo list entity (todo.*).",
        "parameters": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    "ha_create_todo_list": {
        "description": (
            "Create a new Local To-do list (HA local_todo integration). "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "List display name"},
                "confirm": {"type": "boolean"},
            },
            "required": ["name", "confirm"],
        },
    },
    "ha_delete_todo_list": {
        "description": (
            "Delete an entire todo list (removes the local_todo config entry). "
            "Pass entity_id (todo.*) or entry_id. Not for cloud lists (Google etc.) — "
            "those need ha_delete_config_entry on their integration. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "entry_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_clear_todo_list": {
        "description": (
            "Clear items on a todo list. completed_only=true (default) removes finished "
            "items; false removes all items. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "completed_only": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "confirm"],
        },
    },
    "ha_add_todo_item": {
        "description": "Add an item to a todo list. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "item": {"type": "string"},
                "description": {"type": "string"},
                "due_date": {"type": "string"},
                "due_datetime": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "item", "confirm"],
        },
    },
    "ha_update_todo_item": {
        "description": (
            "Update a todo item (rename, status needs_action|completed, due). "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "item": {"type": "string", "description": "Current item uid or summary"},
                "rename": {"type": "string"},
                "status": {"type": "string"},
                "due_date": {"type": "string"},
                "due_datetime": {"type": "string"},
                "description": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "item", "confirm"],
        },
    },
    "ha_remove_todo_item": {
        "description": "Remove a todo item (uid or summary). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "item": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "item", "confirm"],
        },
    },
    "ha_shopping_list": {
        "description": (
            "Legacy shopping_list integration. action=list|add|complete|incomplete|clear|remove. "
            "Cannot delete the shopping_list itself (built-in). Writes need confirm=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "name": {"type": "string", "description": "Item name for add/remove/complete"},
                "item_id": {"type": "string", "description": "Id for update/remove when known"},
                "confirm": {"type": "boolean"},
            },
            "required": ["action"],
        },
    },
    # ── Helpers ───────────────────────────────────────────
    "ha_list_helpers": {
        "description": (
            "List UI-created helpers for a domain "
            "(input_boolean|input_number|input_text|input_select|input_datetime|"
            "input_button|counter|timer|schedule). Omit domain to list all."
        ),
        "parameters": {
            "type": "object",
            "properties": {"domain": {"type": "string"}},
        },
    },
    "ha_create_helper": {
        "description": (
            "Create a helper via storage API. domain + fields (name required; "
            "input_number needs min/max; timer needs duration like '0:05:00'; "
            "schedule needs weekday arrays). confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "fields": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["domain", "fields", "confirm"],
        },
    },
    "ha_update_helper": {
        "description": "Update a helper by storage item_id. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "item_id": {"type": "string"},
                "fields": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["domain", "item_id", "fields", "confirm"],
        },
    },
    "ha_delete_helper": {
        "description": "Delete a UI-created helper by storage item_id. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "item_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["domain", "item_id", "confirm"],
        },
    },
    # ── Traces ────────────────────────────────────────────
    "ha_list_traces": {
        "description": (
            "List recent automation or script execution traces. "
            "domain=automation|script; optional item_id (config id without domain)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "item_id": {"type": "string"},
            },
            "required": ["domain"],
        },
    },
    "ha_get_trace": {
        "description": (
            "Get a full automation/script trace (steps, error, trigger). "
            "Use run_id from ha_list_traces."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "item_id": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["domain", "item_id", "run_id"],
        },
    },
    # ── Notifications ─────────────────────────────────────
    "ha_notify": {
        "description": (
            "Send a notification. service defaults to notify.notify; use notify.mobile_app_* "
            "for phones. Optional data for interactive buttons (actions), image, url, tag, "
            "channel. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "e.g. notify.mobile_app_pixel"},
                "title": {"type": "string"},
                "message": {"type": "string"},
                "target": {"type": "string"},
                "data": {
                    "type": "object",
                    "description": "Platform extras: actions, image, url, tag, channel, …",
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["message", "confirm"],
        },
    },
    "ha_list_persistent_notifications": {
        "description": "List Home Assistant persistent notifications (UI bell).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_create_persistent_notification": {
        "description": "Create a persistent notification. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "title": {"type": "string"},
                "notification_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["message", "confirm"],
        },
    },
    "ha_dismiss_persistent_notification": {
        "description": "Dismiss a persistent notification by id. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "notification_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["notification_id", "confirm"],
        },
    },
    # ── Integrations admin ────────────────────────────────
    "ha_delete_config_entry": {
        "description": "Remove/uninstall a config entry (integration instance). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entry_id", "confirm"],
        },
    },
    "ha_disable_config_entry": {
        "description": (
            "Disable or re-enable a config entry. "
            "disabled_by=user to disable, null/empty to enable. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "disabled_by": {"type": ["string", "null"]},
                "confirm": {"type": "boolean"},
            },
            "required": ["entry_id", "confirm"],
        },
    },
    "ha_update_config_entry": {
        "description": "Update config entry title / prefs. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "title": {"type": "string"},
                "pref_disable_new_entities": {"type": "boolean"},
                "pref_disable_polling": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entry_id", "confirm"],
        },
    },
    "ha_list_integration_handlers": {
        "description": "List integrations that support a config flow (installable domains).",
        "parameters": {
            "type": "object",
            "properties": {"search": {"type": "string"}},
        },
    },
    "ha_start_config_flow": {
        "description": (
            "Start an integration config flow (handler=domain, e.g. mqtt). "
            "Returns flow_id + form fields. OAuth flows may need the UI. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "handler": {"type": "string"},
                "show_advanced_options": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["handler", "confirm"],
        },
    },
    "ha_continue_config_flow": {
        "description": (
            "Continue a config or options flow with user_input. "
            "Set options=true for options flows. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "string"},
                "user_input": {"type": "object"},
                "options": {"type": "boolean", "description": "true for options flow"},
                "confirm": {"type": "boolean"},
            },
            "required": ["flow_id", "confirm"],
        },
    },
    "ha_start_options_flow": {
        "description": "Start options flow for an existing config entry. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entry_id", "confirm"],
        },
    },
    # ── Media players ─────────────────────────────────────
    "ha_media_browse": {
        "description": "Browse a media_player library (optional media_content_type + media_content_id).",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "media_content_type": {"type": "string"},
                "media_content_id": {"type": "string"},
            },
            "required": ["entity_id"],
        },
    },
    "ha_media_search": {
        "description": "Search a media_player library (if supported).",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "search_query": {"type": "string"},
                "media_content_type": {"type": "string"},
                "media_content_id": {"type": "string"},
            },
            "required": ["entity_id", "search_query"],
        },
    },
    "ha_media_play": {
        "description": (
            "Play media on a media_player (media_content_id + media_content_type, "
            "optional enqueue). confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "media_content_id": {"type": "string"},
                "media_content_type": {"type": "string"},
                "enqueue": {"type": "string", "description": "play|next|add|replace"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "media_content_id", "media_content_type", "confirm"],
        },
    },
    "ha_media_control": {
        "description": (
            "Control media_player: media_play|media_pause|media_stop|media_next_track|"
            "media_previous_track|volume_set|volume_mute|volume_up|volume_down|"
            "clear_playlist|shuffle_set|repeat_set|seek. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "action": {"type": "string"},
                "volume_level": {"type": "number", "description": "0.0–1.0 for volume_set"},
                "is_volume_muted": {"type": "boolean"},
                "shuffle": {"type": "boolean"},
                "repeat": {"type": "string"},
                "seek_position": {"type": "number"},
                "confirm": {"type": "boolean"},
            },
            "required": ["entity_id", "action", "confirm"],
        },
    },
    # ── Matter / Thread / Bluetooth ───────────────────────
    "ha_matter": {
        "description": (
            "Matter actions: list_nodes (device registry), commission (code), "
            "commission_on_network (pin), open_commissioning_window, ping_node, "
            "node_diagnostics, set_wifi, set_thread. Use device_id from list_nodes. "
            "Writes need confirm=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "code": {"type": "string", "description": "Commissioning code / QR payload"},
                "pin": {"type": "integer", "description": "PIN for commission_on_network"},
                "device_id": {"type": "string", "description": "HA device registry id"},
                "ssid": {"type": "string"},
                "password": {"type": "string"},
                "dataset": {"type": "string", "description": "Thread dataset TLV for set_thread"},
                "confirm": {"type": "boolean"},
            },
            "required": ["action"],
        },
    },
    "ha_thread": {
        "description": "Thread/OTBR: list_datasets, get_dataset, otbr_info, set_preferred_dataset.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "dataset_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["action"],
        },
    },
    "ha_bluetooth_info": {
        "description": (
            "Bluetooth diagnostics: adapters/scanners from hardware info and "
            "device registry entries with bluetooth connections."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    # ── Scenes CRUD ───────────────────────────────────────
    "ha_get_scene": {
        "description": "Get scene config by config id (from scenes.yaml / entity attributes).",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    "ha_create_scene": {
        "description": (
            "Create a scene (config with name/entities snapshot). "
            "Optional id slug. confirm=true required. Then ha_reload what=scenes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "config": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["config", "confirm"],
        },
    },
    "ha_update_scene": {
        "description": "Update scene config by id. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "config": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["id", "config", "confirm"],
        },
    },
    # ── Recorder ──────────────────────────────────────────
    "ha_recorder_info": {
        "description": "Recorder/database status (recording, backlog, migration).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_recorder_purge": {
        "description": (
            "Purge recorder DB older than keep_days (default instance keep). "
            "repack=true rewrites DB (heavy). confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keep_days": {"type": "integer"},
                "repack": {"type": "boolean"},
                "apply_filter": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_recorder_purge_entities": {
        "description": (
            "Purge history for specific entity_ids, domains, or entity_globs. "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "array", "items": {"type": "string"}},
                "domains": {"type": "array", "items": {"type": "string"}},
                "entity_globs": {"type": "array", "items": {"type": "string"}},
                "keep_days": {"type": "integer"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_recorder_validate": {
        "description": "Validate long-term statistics integrity.",
        "parameters": {"type": "object", "properties": {}},
    },
    # ── HACS ──────────────────────────────────────────────
    "ha_hacs_info": {
        "description": "HACS status (version, stage, disabled reason). Requires HACS installed.",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_hacs_list_repositories": {
        "description": "List HACS repositories. Optional categories filter (integration, plugin, …).",
        "parameters": {
            "type": "object",
            "properties": {
                "categories": {"type": "array", "items": {"type": "string"}},
                "installed_only": {"type": "boolean"},
                "search": {"type": "string"},
            },
        },
    },
    "ha_hacs_repository_info": {
        "description": "Details for one HACS repository (by repository_id).",
        "parameters": {
            "type": "object",
            "properties": {"repository_id": {"type": "string"}},
            "required": ["repository_id"],
        },
    },
    "ha_hacs_install": {
        "description": (
            "Install or update a HACS repository (download). "
            "repository is the id from list/info; optional version. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repository": {"type": "string"},
                "version": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["repository", "confirm"],
        },
    },
    "ha_hacs_remove": {
        "description": "Remove an installed HACS repository. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "repository": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["repository", "confirm"],
        },
    },
}

HANDLERS: dict[str, Any] = {}


def _ha():
    from . import homeassistant as ha
    return ha


def _require_confirm(args: dict) -> str | None:
    return _ha()._require_confirm(args)


def _dump(obj: Any, max_chars: int = 14_000) -> str:
    return _ha()._dump(obj, max_chars=max_chars)


async def _ws(payload: dict, timeout: float = 30.0) -> Any:
    return await _ha()._ws_call(payload, timeout=timeout)


async def _core(method: str, path: str, **kwargs) -> Any:
    return await _ha()._core(method, path, **kwargs)


def _config_id(args: dict, config: dict) -> str:
    raw = (args.get("id") or config.get("id") or config.get("name") or config.get("alias") or "").strip()
    if not raw:
        raise ValueError("id or config.name is required")
    return re.sub(r"[^\w]+", "_", raw.lower()).strip("_") or "scene"


def _helper_domain(raw: str) -> str | None:
    domain = (raw or "").strip().lower()
    return domain if domain in HELPER_DOMAINS else None


# ── Calendar ────────────────────────────────────────────────

async def _list_calendars(_args: dict) -> str:
    rows = await _core("GET", "/calendars")
    return _dump(rows)


async def _list_calendar_events(args: dict) -> str:
    from datetime import datetime, timedelta, timezone

    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    now = datetime.now(timezone.utc).astimezone()
    start = (args.get("start") or now.date().isoformat()).strip()
    end = (args.get("end") or (now.date() + timedelta(days=7)).isoformat()).strip()
    path = f"/calendars/{quote(entity_id, safe='')}?start={quote(start)}&end={quote(end)}"
    events = await _core("GET", path)
    return _dump(events)


async def _create_calendar_event(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    event = args.get("event")
    if not entity_id:
        return "Error: entity_id is required"
    if not isinstance(event, dict):
        return "Error: event must be an object with summary, start, end"
    await _ws({"type": "calendar/event/create", "entity_id": entity_id, "event": event})
    return f"OK: created event on {entity_id}"


async def _update_calendar_event(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    uid = (args.get("uid") or "").strip()
    event = args.get("event")
    if not entity_id or not uid:
        return "Error: entity_id and uid are required"
    if not isinstance(event, dict):
        return "Error: event must be an object"
    payload: dict[str, Any] = {
        "type": "calendar/event/update",
        "entity_id": entity_id,
        "uid": uid,
        "event": event,
    }
    if args.get("recurrence_id"):
        payload["recurrence_id"] = args["recurrence_id"]
    if args.get("recurrence_range"):
        payload["recurrence_range"] = args["recurrence_range"]
    await _ws(payload)
    return f"OK: updated event {uid} on {entity_id}"


async def _delete_calendar_event(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    uid = (args.get("uid") or "").strip()
    if not entity_id or not uid:
        return "Error: entity_id and uid are required"
    payload: dict[str, Any] = {
        "type": "calendar/event/delete",
        "entity_id": entity_id,
        "uid": uid,
    }
    if args.get("recurrence_id"):
        payload["recurrence_id"] = args["recurrence_id"]
    if args.get("recurrence_range"):
        payload["recurrence_range"] = args["recurrence_range"]
    await _ws(payload)
    return f"OK: deleted event {uid} on {entity_id}"


# ── Todo ────────────────────────────────────────────────────

async def _todo_registry_map() -> dict[str, dict]:
    """entity_id → entity registry row."""
    entities = await _ws({"type": "config/entity_registry/list"})
    if not isinstance(entities, list):
        return {}
    return {
        str(e.get("entity_id") or ""): e
        for e in entities
        if isinstance(e, dict) and str(e.get("entity_id") or "").startswith("todo.")
    }


async def _list_todo_lists(args: dict) -> str:
    states = await _ha()._fetch_states_cached()
    reg = await _todo_registry_map()
    search = (args.get("search") or "").strip().lower()
    rows = []
    for st in states:
        eid = st.get("entity_id") or ""
        if not eid.startswith("todo."):
            continue
        name = (st.get("attributes") or {}).get("friendly_name") or eid
        if search and search not in eid.lower() and search not in str(name).lower():
            continue
        meta = reg.get(eid) or {}
        rows.append({
            "entity_id": eid,
            "name": name,
            "state": st.get("state"),
            "platform": meta.get("platform"),
            "config_entry_id": meta.get("config_entry_id"),
            "deletable": meta.get("platform") == "local_todo" and bool(meta.get("config_entry_id")),
        })
    return _dump(rows) if rows else "No todo lists found."


async def _list_todo_items(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    result = await _ws({"type": "todo/item/list", "entity_id": entity_id})
    return _dump(result)


async def _create_todo_list(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    name = (args.get("name") or "").strip()
    if not name:
        return "Error: name is required"
    started = await _core("POST", "/config/config_entries/flow", json_body={"handler": "local_todo"})
    if not isinstance(started, dict) or not started.get("flow_id"):
        return f"Error: could not start local_todo flow\n{_dump(started)}"
    if started.get("type") == "create_entry":
        return f"OK: created todo list '{name}'\n{_dump(started)}"
    flow_id = started["flow_id"]
    result = await _core(
        "POST",
        f"/config/config_entries/flow/{flow_id}",
        json_body={"todo_list_name": name},
    )
    if isinstance(result, dict) and result.get("type") == "create_entry":
        return f"OK: created Local To-do list '{name}'\n{_dump(result)}"
    if isinstance(result, dict) and result.get("type") == "form":
        # retry with errors exposed
        return f"Error: local_todo flow needs more input\n{_dump(result)}"
    return f"OK: local_todo flow finished\n{_dump(result)}"


async def _delete_todo_list(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entry_id = (args.get("entry_id") or "").strip()
    entity_id = (args.get("entity_id") or "").strip()
    if not entry_id and not entity_id:
        return "Error: entity_id or entry_id is required"
    platform = None
    if not entry_id:
        reg = await _todo_registry_map()
        meta = reg.get(entity_id) or {}
        entry_id = (meta.get("config_entry_id") or "").strip()
        platform = meta.get("platform")
        if not entry_id:
            # fallback: match local_todo entries by title / entity slug
            entries = await _ws({"type": "config_entries/get", "domain": "local_todo"})
            rows = entries if isinstance(entries, list) else []
            needle = entity_id.removeprefix("todo.").replace("_", " ").lower()
            name_attr = ""
            try:
                st = await _core("GET", f"/states/{entity_id}")
                if isinstance(st, dict):
                    name_attr = str((st.get("attributes") or {}).get("friendly_name") or "").lower()
            except Exception:
                pass
            for e in rows:
                title = str(e.get("title") or "").lower()
                if title == name_attr or title.replace(" ", "_") == entity_id.removeprefix("todo.") or needle in title:
                    entry_id = str(e.get("entry_id") or "")
                    platform = "local_todo"
                    break
        if not entry_id:
            return (
                f"Error: no config_entry_id for {entity_id}. "
                "Only Local To-do lists can be deleted this way; "
                "cloud lists need ha_delete_config_entry on their integration."
            )
        if platform and platform != "local_todo":
            return (
                f"Error: {entity_id} is platform={platform}, not local_todo. "
                f"Use ha_delete_config_entry entry_id={entry_id} if you really want to remove that integration instance."
            )
    result = await _core("DELETE", f"/config/config_entries/entry/{entry_id}")
    _ha()._STATES_CACHE["ts"] = 0.0
    return f"OK: deleted todo list entry {entry_id}" + (f" ({entity_id})" if entity_id else "") + f"\n{_dump(result)}"


async def _clear_todo_list(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    completed_only = args.get("completed_only")
    if completed_only is None:
        completed_only = True
    if completed_only:
        await _core(
            "POST",
            "/services/todo/remove_completed_items",
            json_body={"entity_id": entity_id},
        )
        return f"OK: removed completed items from {entity_id}"
    result = await _ws({"type": "todo/item/list", "entity_id": entity_id})
    items = []
    if isinstance(result, dict):
        items = result.get("items") or []
    elif isinstance(result, list):
        items = result
    uids = [
        str(it.get("uid") or it.get("summary") or "").strip()
        for it in items
        if isinstance(it, dict)
    ]
    uids = [u for u in uids if u]
    if not uids:
        return f"OK: {entity_id} already empty"
    await _core(
        "POST",
        "/services/todo/remove_item",
        json_body={"entity_id": entity_id, "item": uids},
    )
    return f"OK: removed {len(uids)} items from {entity_id}"


async def _add_todo_item(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    item = (args.get("item") or "").strip()
    if not entity_id or not item:
        return "Error: entity_id and item are required"
    body: dict[str, Any] = {"entity_id": entity_id, "item": item}
    for key in ("description", "due_date", "due_datetime"):
        if args.get(key):
            body[key] = args[key]
    await _core("POST", "/services/todo/add_item", json_body=body)
    return f"OK: added '{item}' to {entity_id}"


async def _update_todo_item(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    item = (args.get("item") or "").strip()
    if not entity_id or not item:
        return "Error: entity_id and item are required"
    body: dict[str, Any] = {"entity_id": entity_id, "item": item}
    for key in ("rename", "status", "due_date", "due_datetime", "description"):
        if args.get(key) is not None and args.get(key) != "":
            body[key] = args[key]
    await _core("POST", "/services/todo/update_item", json_body=body)
    return f"OK: updated item on {entity_id}"


async def _remove_todo_item(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    item = (args.get("item") or "").strip()
    if not entity_id or not item:
        return "Error: entity_id and item are required"
    # Resolve summary → uid when needed
    try:
        listed = await _ws({"type": "todo/item/list", "entity_id": entity_id})
        rows = (listed.get("items") if isinstance(listed, dict) else listed) or []
        if isinstance(rows, list):
            for it in rows:
                if not isinstance(it, dict):
                    continue
                if str(it.get("uid") or "") == item or str(it.get("summary") or "").lower() == item.lower():
                    item = str(it.get("uid") or item)
                    break
    except Exception:
        pass
    await _core(
        "POST",
        "/services/todo/remove_item",
        json_body={"entity_id": entity_id, "item": [item]},
    )
    return f"OK: removed item from {entity_id}"


async def _shopping_list(args: dict) -> str:
    action = (args.get("action") or "list").strip().lower()
    if action == "list":
        return _dump(await _ws({"type": "shopping_list/items"}))
    if msg := _require_confirm(args):
        return msg
    name = (args.get("name") or "").strip()
    item_id = (args.get("item_id") or "").strip()
    if action == "add":
        if not name:
            return "Error: name is required"
        await _ws({"type": "shopping_list/items/add", "name": name})
        return f"OK: added '{name}' to shopping list"
    if action == "clear":
        await _ws({"type": "shopping_list/items/clear"})
        return "OK: cleared completed shopping list items"
    if action in ("complete", "incomplete", "update"):
        payload: dict[str, Any] = {"type": "shopping_list/items/update"}
        if item_id:
            payload["item_id"] = item_id
        elif name:
            # resolve by name
            items = await _ws({"type": "shopping_list/items"})
            rows = items if isinstance(items, list) else []
            match = next((r for r in rows if str(r.get("name") or "").lower() == name.lower()), None)
            if not match:
                return f"Error: item '{name}' not found"
            payload["item_id"] = match.get("id")
        else:
            return "Error: name or item_id required"
        payload["complete"] = action != "incomplete"
        if name and action == "update":
            payload["name"] = name
        await _ws(payload)
        return f"OK: shopping list item updated ({action})"
    if action == "remove":
        payload = {"type": "shopping_list/items/remove"}
        if item_id:
            payload["item_id"] = item_id
        elif name:
            items = await _ws({"type": "shopping_list/items"})
            rows = items if isinstance(items, list) else []
            match = next((r for r in rows if str(r.get("name") or "").lower() == name.lower()), None)
            if not match:
                return f"Error: item '{name}' not found"
            payload["item_id"] = match.get("id")
        else:
            return "Error: name or item_id required"
        await _ws(payload)
        return "OK: removed shopping list item"
    return "Error: action must be list|add|complete|incomplete|clear|remove|update"


# ── Helpers ─────────────────────────────────────────────────

async def _list_helpers(args: dict) -> str:
    domain = (args.get("domain") or "").strip().lower()
    domains = [domain] if domain else list(HELPER_DOMAINS)
    if domain and domain not in HELPER_DOMAINS:
        return f"Error: domain must be one of {', '.join(HELPER_DOMAINS)}"
    out: dict[str, Any] = {}
    for d in domains:
        try:
            out[d] = await _ws({"type": f"{d}/list"})
        except Exception as e:
            out[d] = {"error": str(e)}
    return _dump(out)


async def _create_helper(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    domain = _helper_domain(args.get("domain") or "")
    fields = args.get("fields")
    if not domain:
        return f"Error: domain must be one of {', '.join(HELPER_DOMAINS)}"
    if not isinstance(fields, dict) or not fields.get("name"):
        return "Error: fields.name is required"
    result = await _ws({"type": f"{domain}/create", **fields})
    return f"OK: created {domain}\n{_dump(result)}"


async def _update_helper(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    domain = _helper_domain(args.get("domain") or "")
    item_id = (args.get("item_id") or "").strip()
    fields = args.get("fields")
    if not domain:
        return f"Error: domain must be one of {', '.join(HELPER_DOMAINS)}"
    if not item_id:
        return "Error: item_id is required"
    if not isinstance(fields, dict):
        return "Error: fields must be an object"
    result = await _ws({"type": f"{domain}/update", "item_id": item_id, **fields})
    return f"OK: updated {domain}/{item_id}\n{_dump(result)}"


async def _delete_helper(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    domain = _helper_domain(args.get("domain") or "")
    item_id = (args.get("item_id") or "").strip()
    if not domain:
        return f"Error: domain must be one of {', '.join(HELPER_DOMAINS)}"
    if not item_id:
        return "Error: item_id is required"
    await _ws({"type": f"{domain}/delete", "item_id": item_id})
    return f"OK: deleted {domain}/{item_id}"


# ── Traces ──────────────────────────────────────────────────

async def _list_traces(args: dict) -> str:
    domain = (args.get("domain") or "").strip().lower()
    if domain not in ("automation", "script"):
        return "Error: domain must be automation or script"
    payload: dict[str, Any] = {"type": "trace/list", "domain": domain}
    item_id = (args.get("item_id") or "").strip()
    if item_id:
        # accept automation.xxx and strip
        if item_id.startswith(f"{domain}."):
            item_id = item_id.split(".", 1)[1]
        payload["item_id"] = item_id
    result = await _ws(payload)
    return _dump(result)


async def _get_trace(args: dict) -> str:
    domain = (args.get("domain") or "").strip().lower()
    item_id = (args.get("item_id") or "").strip()
    run_id = (args.get("run_id") or "").strip()
    if domain not in ("automation", "script"):
        return "Error: domain must be automation or script"
    if not item_id or not run_id:
        return "Error: item_id and run_id are required"
    if item_id.startswith(f"{domain}."):
        item_id = item_id.split(".", 1)[1]
    result = await _ws({
        "type": "trace/get",
        "domain": domain,
        "item_id": item_id,
        "run_id": run_id,
    })
    return _dump(result, max_chars=20_000)


# ── Notifications ───────────────────────────────────────────

async def _notify(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    message = (args.get("message") or "").strip()
    if not message:
        return "Error: message is required"
    service = (args.get("service") or "notify.notify").strip()
    if "." not in service:
        service = f"notify.{service}"
    domain, svc = service.split(".", 1)
    body: dict[str, Any] = {"message": message}
    if args.get("title"):
        body["title"] = args["title"]
    if args.get("target"):
        body["target"] = args["target"]
    data = args.get("data")
    if isinstance(data, dict) and data:
        body["data"] = data
    await _core("POST", f"/services/{domain}/{svc}", json_body=body)
    return f"OK: sent notification via {service}"


async def _list_persistent_notifications(_args: dict) -> str:
    try:
        result = await _ws({"type": "persistent_notification/get"})
    except Exception:
        # Older HA: fall back to states
        states = await _ha()._fetch_states_cached()
        result = [
            {
                "notification_id": (st.get("entity_id") or "").removeprefix("persistent_notification."),
                "title": (st.get("attributes") or {}).get("title"),
                "message": st.get("state"),
            }
            for st in states
            if (st.get("entity_id") or "").startswith("persistent_notification.")
        ]
    return _dump(result)


async def _create_persistent_notification(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    message = (args.get("message") or "").strip()
    if not message:
        return "Error: message is required"
    body: dict[str, Any] = {"message": message}
    if args.get("title"):
        body["title"] = args["title"]
    if args.get("notification_id"):
        body["notification_id"] = args["notification_id"]
    await _core("POST", "/services/persistent_notification/create", json_body=body)
    return "OK: persistent notification created"


async def _dismiss_persistent_notification(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    nid = (args.get("notification_id") or "").strip()
    if not nid:
        return "Error: notification_id is required"
    await _core(
        "POST",
        "/services/persistent_notification/dismiss",
        json_body={"notification_id": nid},
    )
    return f"OK: dismissed {nid}"


# ── Integrations ────────────────────────────────────────────

async def _delete_config_entry(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entry_id = (args.get("entry_id") or "").strip()
    if not entry_id:
        return "Error: entry_id is required"
    result = await _core("DELETE", f"/config/config_entries/entry/{entry_id}")
    return f"OK: removed config entry {entry_id}\n{_dump(result)}"


async def _disable_config_entry(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entry_id = (args.get("entry_id") or "").strip()
    if not entry_id:
        return "Error: entry_id is required"
    disabled_by = args.get("disabled_by", "user")
    if disabled_by in ("", "null", "none", None):
        disabled_by = None
    result = await _ws({
        "type": "config_entries/disable",
        "entry_id": entry_id,
        "disabled_by": disabled_by,
    })
    return f"OK: config entry {entry_id} disabled_by={disabled_by}\n{_dump(result)}"


async def _update_config_entry(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entry_id = (args.get("entry_id") or "").strip()
    if not entry_id:
        return "Error: entry_id is required"
    payload: dict[str, Any] = {"type": "config_entries/update", "entry_id": entry_id}
    for key in ("title", "pref_disable_new_entities", "pref_disable_polling"):
        if key in args and args[key] is not None:
            payload[key] = args[key]
    result = await _ws(payload)
    return f"OK: updated config entry {entry_id}\n{_dump(result)}"


async def _list_integration_handlers(args: dict) -> str:
    rows = await _core("GET", "/config/config_entries/flow_handlers")
    search = (args.get("search") or "").strip().lower()
    if search and isinstance(rows, list):
        rows = [
            r for r in rows
            if search in str(r.get("handler") or r.get("domain") or r).lower()
            or search in str(r.get("name") or "").lower()
        ]
    return _dump(rows)


async def _start_config_flow(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    handler = (args.get("handler") or "").strip()
    if not handler:
        return "Error: handler (integration domain) is required"
    body: dict[str, Any] = {"handler": handler}
    if args.get("show_advanced_options"):
        body["show_advanced_options"] = True
    result = await _core("POST", "/config/config_entries/flow", json_body=body)
    return _dump(result)


async def _continue_config_flow(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    flow_id = (args.get("flow_id") or "").strip()
    if not flow_id:
        return "Error: flow_id is required"
    user_input = args.get("user_input") if isinstance(args.get("user_input"), dict) else {}
    base = (
        "/config/config_entries/options/flow"
        if args.get("options")
        else "/config/config_entries/flow"
    )
    result = await _core("POST", f"{base}/{flow_id}", json_body=user_input)
    return _dump(result)


async def _start_options_flow(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entry_id = (args.get("entry_id") or "").strip()
    if not entry_id:
        return "Error: entry_id is required"
    result = await _core(
        "POST",
        "/config/config_entries/options/flow",
        json_body={"handler": entry_id},
    )
    return _dump(result)


# ── Media ───────────────────────────────────────────────────

async def _media_browse(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    if not entity_id:
        return "Error: entity_id is required"
    payload: dict[str, Any] = {"type": "media_player/browse_media", "entity_id": entity_id}
    if args.get("media_content_type") and args.get("media_content_id") is not None:
        payload["media_content_type"] = args["media_content_type"]
        payload["media_content_id"] = args["media_content_id"]
    return _dump(await _ws(payload))


async def _media_search(args: dict) -> str:
    entity_id = (args.get("entity_id") or "").strip()
    query = (args.get("search_query") or "").strip()
    if not entity_id or not query:
        return "Error: entity_id and search_query are required"
    payload: dict[str, Any] = {
        "type": "media_player/search_media",
        "entity_id": entity_id,
        "search_query": query,
    }
    if args.get("media_content_type") and args.get("media_content_id") is not None:
        payload["media_content_type"] = args["media_content_type"]
        payload["media_content_id"] = args["media_content_id"]
    return _dump(await _ws(payload))


async def _media_play(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    content_id = (args.get("media_content_id") or "").strip()
    content_type = (args.get("media_content_type") or "").strip()
    if not entity_id or not content_id or not content_type:
        return "Error: entity_id, media_content_id, media_content_type required"
    body: dict[str, Any] = {
        "entity_id": entity_id,
        "media_content_id": content_id,
        "media_content_type": content_type,
    }
    if args.get("enqueue"):
        body["enqueue"] = args["enqueue"]
    await _core("POST", "/services/media_player/play_media", json_body=body)
    return f"OK: play_media on {entity_id}"


_MEDIA_ACTIONS = {
    "media_play", "media_pause", "media_stop", "media_next_track", "media_previous_track",
    "volume_set", "volume_mute", "volume_up", "volume_down",
    "clear_playlist", "shuffle_set", "repeat_set", "media_seek", "seek",
}


async def _media_control(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    entity_id = (args.get("entity_id") or "").strip()
    action = (args.get("action") or "").strip()
    if action == "seek":
        action = "media_seek"
    if not entity_id or action not in _MEDIA_ACTIONS:
        return f"Error: entity_id and action in {sorted(_MEDIA_ACTIONS)} required"
    body: dict[str, Any] = {"entity_id": entity_id}
    if action == "volume_set":
        if args.get("volume_level") is None:
            return "Error: volume_level (0–1) required for volume_set"
        body["volume_level"] = float(args["volume_level"])
    if action == "volume_mute" and args.get("is_volume_muted") is not None:
        body["is_volume_muted"] = bool(args["is_volume_muted"])
    if action == "shuffle_set" and args.get("shuffle") is not None:
        body["shuffle"] = bool(args["shuffle"])
    if action == "repeat_set" and args.get("repeat"):
        body["repeat"] = args["repeat"]
    if action == "media_seek":
        if args.get("seek_position") is None:
            return "Error: seek_position required"
        body["seek_position"] = float(args["seek_position"])
    await _core("POST", f"/services/media_player/{action}", json_body=body)
    return f"OK: {action} on {entity_id}"


# ── Matter / Thread / BT ────────────────────────────────────

async def _matter(args: dict) -> str:
    action = (args.get("action") or "").strip().lower()
    if action in ("list_nodes", "list"):
        _, _, devices, _, _ = await _ha()._fetch_registry_bundle()
        nodes = []
        for d in devices:
            idents = d.get("identifiers") or []
            if any(isinstance(i, (list, tuple)) and i and i[0] == "matter" for i in idents):
                nodes.append({
                    "id": d.get("id"),
                    "name": d.get("name_by_user") or d.get("name"),
                    "manufacturer": d.get("manufacturer"),
                    "model": d.get("model"),
                    "identifiers": idents,
                    "area_id": d.get("area_id"),
                })
        return _dump(nodes) if nodes else "No Matter devices in registry."

    write_actions = {
        "commission", "commission_on_network", "open_commissioning_window",
        "set_wifi", "set_thread",
    }
    if action in write_actions:
        if msg := _require_confirm(args):
            return msg

    if action == "commission":
        code = (args.get("code") or "").strip()
        if not code:
            return "Error: code required"
        return _dump(await _ws({"type": "matter/commission", "code": code}))
    if action == "commission_on_network":
        pin = args.get("pin")
        if pin is None:
            return "Error: pin (integer) required for commission_on_network"
        payload: dict[str, Any] = {"type": "matter/commission_on_network", "pin": int(pin)}
        if args.get("code"):  # optional ip via unused; keep pin-only
            pass
        return _dump(await _ws(payload))
    device_id = (args.get("device_id") or args.get("node_id") or "").strip()
    if action in ("open_commissioning_window", "ping_node", "node_diagnostics"):
        if not device_id:
            return "Error: device_id required (from list_nodes)"
        type_map = {
            "open_commissioning_window": "matter/open_commissioning_window",
            "ping_node": "matter/ping_node",
            "node_diagnostics": "matter/node_diagnostics",
        }
        return _dump(await _ws({"type": type_map[action], "device_id": device_id}))
    if action == "set_wifi":
        ssid = (args.get("ssid") or "").strip()
        password = args.get("password") or ""
        if not ssid:
            return "Error: ssid required"
        await _ws({
            "type": "matter/set_wifi_credentials",
            "network_name": ssid,
            "password": password,
        })
        return "OK: Matter Wi-Fi credentials set"
    if action == "set_thread":
        dataset = (args.get("dataset") or "").strip()
        if not dataset:
            return "Error: dataset (TLV) required"
        await _ws({"type": "matter/set_thread", "thread_operation_dataset": dataset})
        return "OK: Matter Thread dataset set"
    return (
        "Error: action must be list_nodes|commission|commission_on_network|"
        "open_commissioning_window|ping_node|node_diagnostics|set_wifi|set_thread"
    )


async def _thread(args: dict) -> str:
    action = (args.get("action") or "").strip().lower()
    if action == "list_datasets":
        return _dump(await _ws({"type": "thread/list_datasets"}))
    if action == "get_dataset":
        dataset_id = (args.get("dataset_id") or "").strip()
        if not dataset_id:
            return "Error: dataset_id required"
        return _dump(await _ws({"type": "thread/get_dataset_tlv", "dataset_id": dataset_id}))
    if action == "otbr_info":
        return _dump(await _ws({"type": "otbr/info"}))
    if action == "set_preferred_dataset":
        if msg := _require_confirm(args):
            return msg
        dataset_id = (args.get("dataset_id") or "").strip()
        if not dataset_id:
            return "Error: dataset_id required"
        await _ws({"type": "thread/set_preferred_dataset", "dataset_id": dataset_id})
        return f"OK: preferred Thread dataset set to {dataset_id}"
    return "Error: action must be list_datasets|get_dataset|otbr_info|set_preferred_dataset"


async def _bluetooth_info(_args: dict) -> str:
    out: dict[str, Any] = {}
    try:
        out["hardware"] = await _ws({"type": "hardware/info"})
    except Exception as e:
        out["hardware_error"] = str(e)
    _, _, devices, _, _ = await _ha()._fetch_registry_bundle()
    bt = []
    for d in devices:
        conns = d.get("connections") or []
        if any(isinstance(c, (list, tuple)) and c and c[0] == "bluetooth" for c in conns):
            bt.append({
                "id": d.get("id"),
                "name": d.get("name_by_user") or d.get("name"),
                "connections": conns,
                "manufacturer": d.get("manufacturer"),
                "model": d.get("model"),
                "area_id": d.get("area_id"),
            })
    out["bluetooth_devices"] = bt
    return _dump(out)


# ── Scenes ──────────────────────────────────────────────────

async def _get_scene(args: dict) -> str:
    cid = (args.get("id") or "").strip()
    if not cid:
        return "Error: id is required"
    if cid.startswith("scene."):
        cid = cid.split(".", 1)[1]
    result = await _core("GET", f"/config/scene/config/{cid}")
    return _dump(result)


async def _create_scene(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    config = args.get("config")
    if not isinstance(config, dict):
        return "Error: config must be an object"
    try:
        cid = _config_id(args, config)
    except ValueError as e:
        return f"Error: {e}"
    body = dict(config)
    body.setdefault("id", cid)
    await _core("POST", f"/config/scene/config/{cid}", json_body=body)
    return f"OK: created scene id={cid}. Run ha_reload what=scenes confirm=true."


async def _update_scene(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    cid = (args.get("id") or "").strip()
    config = args.get("config")
    if not cid:
        return "Error: id is required"
    if not isinstance(config, dict):
        return "Error: config must be an object"
    if cid.startswith("scene."):
        cid = cid.split(".", 1)[1]
    body = dict(config)
    body["id"] = cid
    await _core("POST", f"/config/scene/config/{cid}", json_body=body)
    return f"OK: updated scene id={cid}. Run ha_reload what=scenes confirm=true."


# ── Recorder ────────────────────────────────────────────────

async def _recorder_info(_args: dict) -> str:
    return _dump(await _ws({"type": "recorder/info"}))


async def _recorder_purge(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    body: dict[str, Any] = {}
    if args.get("keep_days") is not None:
        body["keep_days"] = int(args["keep_days"])
    if args.get("repack"):
        body["repack"] = True
    if args.get("apply_filter"):
        body["apply_filter"] = True
    await _core("POST", "/services/recorder/purge", json_body=body or None)
    return f"OK: recorder.purge started\n{_dump(body or {'keep_days': 'default'})}"


async def _recorder_purge_entities(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    body: dict[str, Any] = {}
    for key in ("entity_id", "domains", "entity_globs"):
        val = args.get(key)
        if isinstance(val, list) and val:
            body[key] = val
        elif isinstance(val, str) and val.strip():
            body[key] = [val.strip()]
    if not body:
        return "Error: provide entity_id, domains, and/or entity_globs"
    if args.get("keep_days") is not None:
        body["keep_days"] = int(args["keep_days"])
    await _core("POST", "/services/recorder/purge_entities", json_body=body)
    return f"OK: recorder.purge_entities started\n{_dump(body)}"


async def _recorder_validate(_args: dict) -> str:
    return _dump(await _ws({"type": "recorder/validate_statistics"}))


# ── HACS ────────────────────────────────────────────────────

async def _hacs_info(_args: dict) -> str:
    return _dump(await _ws({"type": "hacs/info"}))


async def _hacs_list_repositories(args: dict) -> str:
    payload: dict[str, Any] = {"type": "hacs/repositories/list"}
    cats = args.get("categories")
    if isinstance(cats, list) and cats:
        payload["categories"] = cats
    rows = await _ws(payload)
    if not isinstance(rows, list):
        return _dump(rows)
    search = (args.get("search") or "").strip().lower()
    installed_only = bool(args.get("installed_only"))
    filtered = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if installed_only and not r.get("installed"):
            continue
        blob = " ".join(
            str(r.get(k) or "")
            for k in ("full_name", "name", "description", "category", "id")
        ).lower()
        if search and search not in blob:
            continue
        filtered.append({
            "id": r.get("id"),
            "full_name": r.get("full_name") or r.get("name"),
            "category": r.get("category"),
            "installed": r.get("installed"),
            "available_version": r.get("available_version") or r.get("pending_upgrade"),
            "installed_version": r.get("installed_version") or r.get("version_installed"),
            "new": r.get("new"),
        })
    return _dump(filtered[:200])


async def _hacs_repository_info(args: dict) -> str:
    rid = (args.get("repository_id") or "").strip()
    if not rid:
        return "Error: repository_id is required"
    return _dump(await _ws({"type": "hacs/repository/info", "repository_id": rid}))


async def _hacs_install(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    repo = (args.get("repository") or "").strip()
    if not repo:
        return "Error: repository is required"
    payload: dict[str, Any] = {"type": "hacs/repository/download", "repository": repo}
    if args.get("version"):
        payload["version"] = str(args["version"])
    result = await _ws(payload, timeout=120.0)
    return f"OK: HACS download started for {repo}\n{_dump(result)}"


async def _hacs_remove(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    repo = (args.get("repository") or "").strip()
    if not repo:
        return "Error: repository is required"
    await _ws({"type": "hacs/repository/remove", "repository": repo})
    return f"OK: removed HACS repository {repo}"


HANDLERS.update({
    "ha_list_calendars": _list_calendars,
    "ha_list_calendar_events": _list_calendar_events,
    "ha_create_calendar_event": _create_calendar_event,
    "ha_update_calendar_event": _update_calendar_event,
    "ha_delete_calendar_event": _delete_calendar_event,
    "ha_list_todo_lists": _list_todo_lists,
    "ha_list_todo_items": _list_todo_items,
    "ha_create_todo_list": _create_todo_list,
    "ha_delete_todo_list": _delete_todo_list,
    "ha_clear_todo_list": _clear_todo_list,
    "ha_add_todo_item": _add_todo_item,
    "ha_update_todo_item": _update_todo_item,
    "ha_remove_todo_item": _remove_todo_item,
    "ha_shopping_list": _shopping_list,
    "ha_list_helpers": _list_helpers,
    "ha_create_helper": _create_helper,
    "ha_update_helper": _update_helper,
    "ha_delete_helper": _delete_helper,
    "ha_list_traces": _list_traces,
    "ha_get_trace": _get_trace,
    "ha_notify": _notify,
    "ha_list_persistent_notifications": _list_persistent_notifications,
    "ha_create_persistent_notification": _create_persistent_notification,
    "ha_dismiss_persistent_notification": _dismiss_persistent_notification,
    "ha_delete_config_entry": _delete_config_entry,
    "ha_disable_config_entry": _disable_config_entry,
    "ha_update_config_entry": _update_config_entry,
    "ha_list_integration_handlers": _list_integration_handlers,
    "ha_start_config_flow": _start_config_flow,
    "ha_continue_config_flow": _continue_config_flow,
    "ha_start_options_flow": _start_options_flow,
    "ha_media_browse": _media_browse,
    "ha_media_search": _media_search,
    "ha_media_play": _media_play,
    "ha_media_control": _media_control,
    "ha_matter": _matter,
    "ha_thread": _thread,
    "ha_bluetooth_info": _bluetooth_info,
    "ha_get_scene": _get_scene,
    "ha_create_scene": _create_scene,
    "ha_update_scene": _update_scene,
    "ha_recorder_info": _recorder_info,
    "ha_recorder_purge": _recorder_purge,
    "ha_recorder_purge_entities": _recorder_purge_entities,
    "ha_recorder_validate": _recorder_validate,
    "ha_hacs_info": _hacs_info,
    "ha_hacs_list_repositories": _hacs_list_repositories,
    "ha_hacs_repository_info": _hacs_repository_info,
    "ha_hacs_install": _hacs_install,
    "ha_hacs_remove": _hacs_remove,
})
