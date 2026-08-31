"""Pure Home Assistant entity helpers (testable without a live instance)."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_HA_AGENT_PROMPT = """You are the Home Assistant administrator copilot. Available tools: {tools}.

Chain tools until the job is done — do not stop after a single lookup.
Read-only questions (explain, what does X do, list, show): usually 1–3 tool calls, then answer in plain language — do not loop tools or narrate internal reasoning.

Entities (live state via REST):
- Find: ha_list_entities (search, domain, area_name, offset; registry columns when available) → ha_get_state
- Device status ("is it on/running?", "merge irigatorul?", "e pornit X?", "what is X doing now?"): search the physical entity (switch, valve, binary_sensor, sensor, irrigation, pump, …) → ha_get_state — answer from live state (on/off/unavailable). Do NOT use ha_list_automations / ha_get_automation for device status; automations are rules, not the device itself.
- Lights / bulbs / lamps: many homes wire them through relays as switch.* — never assume domain=light only. Prefer search= (and area_name=) without locking domain, or domain=light,switch. Call switch.turn_on / switch.turn_off when the match is a switch.
- Registry metadata: ha_list_entity_registry / ha_get_entity_registry — names, areas, devices, disabled/hidden
- Rename/move/disable: ha_update_entity (confirm=true); resolve area with ha_list_areas
- Rooms: ha_create_area / ha_update_area; labels: ha_list_labels → ha_create_label → assign on entity/device
- Move device + all its entities: ha_update_device (area_name/area_id, confirm=true)
- Helpers only: ha_set_state for values; create/delete with ha_list_helpers → ha_create_helper / ha_update_helper / ha_delete_helper (confirm=true)
- Act: ha_list_services(domain=…) → ha_call_service → ha_get_state to verify; service domain must match the entity domain (light.* → light.turn_*, switch.* → switch.turn_*)
- area_id in registry, not state.attributes — use ha_list_areas for room names
- If state is unavailable or unknown, diagnose before calling services
- Trace: ha_get_history / ha_get_logbook for recent changes; ha_get_entity_source for integration; failed automations → ha_list_traces → ha_get_trace
- Voice/Assist: ha_list_exposed_entities → ha_expose_entity (confirm=true; assistant conversation by default)
- Floors: ha_list_floors → ha_create_area with floor_name or ha_update_area
- Automations/scripts/scenes: ha_list_* (search) → ha_get_* (config + triggers/actions) when the user asks about rules, schedules, triggers, or what an automation does — not when they ask if a device is currently on/running. Explain-only: stop after ha_get_* — do not call delete/mutate tools. Create/edit scenes: ha_create_scene / ha_update_scene.
- Calendar/todo: ha_list_calendars → ha_list_calendar_events; create/update/delete events; todo lists via ha_list_todo_* / ha_create_todo_list / ha_delete_todo_list / ha_clear_todo_list / ha_add_todo_item; legacy shopping_list via ha_shopping_list (cannot delete the built-in shopping list itself)
- Notifications: ha_notify (mobile actions/images in data); persistent_notification tools for UI bell
- Media players: ha_media_browse / ha_media_search → ha_media_play / ha_media_control
- Integrations: ha_list_config_entries → ha_get_config_entry; reload/disable/delete; install via ha_list_integration_handlers → ha_start_config_flow → ha_continue_config_flow (OAuth may need UI)
- Matter/Thread/BT: ha_matter / ha_thread / ha_bluetooth_info; Zigbee/Z-Wave: ha_mesh_network
- Recorder: ha_recorder_info → ha_recorder_purge / ha_recorder_purge_entities (confirm=true)
- HACS: ha_hacs_list_repositories → ha_hacs_install / ha_hacs_remove (confirm=true)
- Long-term sensors: ha_list_statistic_ids → ha_get_statistics; groups/zones/persons: ha_list_groups / ha_list_zones / ha_list_persons

Dashboards (WebSocket, storage mode):
- ha_list_dashboards → ha_get_dashboard (summary) → ha_upsert_view / ha_upsert_section / ha_upsert_card / ha_delete_card / ha_delete_view
- Dashboard delete/update: use dashboard_id from ha_list_dashboards (not url_path alone)
- Overview/default uses empty url_path; user pages are views (view_path)
- dashboard_url (/lovelace/foo or /dashboard-bar/baz) resolves url_path + view_path
- Sections views: cards in sections[].cards — pass section_index or create_section=true
- Nested stack/grid cards: card_path like 2.1
- YAML dashboards: ha_append_card_yaml or ha_read_file / ha_write_file, then ha_reload what=lovelace confirm=true

Diagnose: ha_list_problems + ha_get_logs.
Config files: ha_read_file / ha_write_file → ha_check_config → ha_reload if needed.
Custom integration .py: only if Settings → HA tools → Custom component Python (custom_code) is ON. Then ha_read_file → ha_write_file confirm=false (show the diff to the user and ask) → after they agree ha_write_file confirm=true with change_summary (writes .bak first). Never edit .py outside custom_components.
Mutating tools need confirm=true when the user already asked you to make the change."""

COMPACT_HA_AGENT_PROMPT = """Home Assistant copilot. Tools: {tools}.

Simple commands (lights, switches, status): ha_list_entities → ha_get_state → ha_call_service (confirm=true for writes).
Device on/off/running: read entity state — not automations. Lights may be switch.* relays.
Mutations need confirm=true. Stop after the job is done — no narration."""

HA_ENTITY_TOOLS = frozenset({
    "ha_list_entities",
    "ha_get_state",
    "ha_call_service",
    "ha_list_services",
    "ha_list_entity_registry",
    "ha_get_entity_registry",
    "ha_list_areas",
    "ha_list_devices",
    "ha_get_device",
    "ha_list_labels",
    "ha_get_history",
    "ha_get_logbook",
    "ha_get_entity_source",
    "ha_list_exposed_entities",
    "ha_list_floors",
    "ha_list_automations",
    "ha_get_automation",
    "ha_list_scripts",
    "ha_list_scenes",
    "ha_list_config_entries",
    "ha_get_config_entry",
    "ha_list_statistic_ids",
    "ha_get_statistics",
    "ha_list_groups",
    "ha_list_zones",
    "ha_list_persons",
})

HA_REGISTRY_MUTATING_TOOLS = frozenset({
    "ha_update_entity",
    "ha_set_state",
    "ha_create_area",
    "ha_update_area",
    "ha_create_label",
    "ha_update_label",
    "ha_update_device",
    "ha_expose_entity",
    "ha_create_floor",
    "ha_update_floor",
    "ha_trigger_automation",
    "ha_run_script",
    "ha_activate_scene",
    "ha_delete_automation",
    "ha_delete_script",
    "ha_delete_scene",
    "ha_reload_config_entry",
})

_STATE_SET_DOMAINS = frozenset({
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
})

_LEGACY_DEFAULT_DOMAINS = frozenset({
    "light", "switch", "climate", "cover", "fan", "lock", "media_player",
    "vacuum", "scene", "script", "input_boolean", "input_button",
    "binary_sensor", "sensor", "automation", "person", "device_tracker",
})

_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "light": ("brightness", "color_temp", "rgb_color", "effect", "transition"),
    "climate": ("temperature", "target_temp_high", "target_temp_low", "hvac_mode", "preset_mode"),
    "cover": ("position", "tilt_position"),
    "fan": ("percentage", "preset_mode", "oscillating"),
    "media_player": ("volume_level", "media_player.play_media", "source"),
}


def domain_of(entity_id: str) -> str:
    return (entity_id or "").split(".", 1)[0].lower()


# domain=light also matches switch.* — many "lights" are relay switches.
_DOMAIN_EXPAND = {
    "light": frozenset({"light", "switch"}),
    "lights": frozenset({"light", "switch"}),
}


def parse_domains(raw) -> frozenset[str]:
    """Parse domain= filter: comma-separated, with light → light+switch expansion."""
    text = str(raw or "").strip().lower()
    if not text:
        return frozenset()
    out: set[str] = set()
    for part in text.replace(";", ",").split(","):
        dom = part.strip()
        if not dom:
            continue
        out.update(_DOMAIN_EXPAND.get(dom, (dom,)))
    return frozenset(out)


def entity_matches_domains(entity_id: str, domains: frozenset[str]) -> bool:
    if not domains:
        return True
    return domain_of(entity_id) in domains


def filter_states(states: list[dict], args: dict) -> list[dict]:
    domains = parse_domains(args.get("domain"))
    search = (args.get("search") or "").strip().lower()
    state_filter = (args.get("state_filter") or "").strip().lower()
    include_all = args.get("include_all_domains")
    if include_all is None:
        include_all = True if (domains or search) else True

    rows: list[dict] = []
    for st in states:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        if not eid:
            continue
        if not entity_matches_domains(eid, domains):
            continue
        if not domains and not search and not include_all:
            if domain_of(eid) not in _LEGACY_DEFAULT_DOMAINS:
                continue
        attrs = st.get("attributes") or {}
        fname = str(attrs.get("friendly_name") or "")
        if search and search not in eid.lower() and search not in fname.lower():
            continue
        state_val = str(st.get("state") or "").lower()
        if state_filter and state_filter != state_val:
            continue
        rows.append(st)
    return rows


def sort_states(states: list[dict], sort_key: str | None) -> list[dict]:
    key = (sort_key or "entity_id").strip().lower()
    if key == "name":

        def sort_name(st: dict) -> str:
            attrs = st.get("attributes") or {}
            return str(attrs.get("friendly_name") or st.get("entity_id") or "").lower()

        return sorted(states, key=sort_name)
    if key == "state":

        def sort_state(st: dict) -> str:
            return str(st.get("state") or "").lower()

        return sorted(states, key=sort_state)
    return sorted(states, key=lambda st: str(st.get("entity_id") or "").lower())


def paginate_states(states: list[dict], limit: int, offset: int) -> tuple[list[dict], int]:
    limit = max(1, min(int(limit or 40), 120))
    offset = max(0, int(offset or 0))
    total = len(states)
    return states[offset : offset + limit], total


def format_entity_row(st: dict) -> str:
    eid = st.get("entity_id") or "?"
    attrs = st.get("attributes") or {}
    fname = str(attrs.get("friendly_name") or "")
    state_val = st.get("state") or "?"
    dom = domain_of(str(eid))
    return f"{eid}|{fname}|{state_val}|{dom}"


def format_entity_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching entities."
    lines = ["entity_id|name|state|domain"]
    lines.extend(format_entity_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def decode_capabilities(domain: str, attrs: dict) -> list[str]:
    hints = list(_CAPABILITY_HINTS.get(domain, ()))
    if domain == "light":
        modes = attrs.get("supported_color_modes") or []
        if modes:
            hints.append(f"color_modes={','.join(str(m) for m in modes)}")
    if domain == "climate":
        for key in ("hvac_modes", "preset_modes", "fan_modes"):
            vals = attrs.get(key)
            if vals:
                hints.append(f"{key}={','.join(str(v) for v in vals)}")
    min_temp = attrs.get("min_temp")
    max_temp = attrs.get("max_temp")
    if min_temp is not None and max_temp is not None:
        hints.append(f"temp_range={min_temp}-{max_temp}")
    return hints


def format_state_detail(state: dict, args: dict) -> str:
    eid = state.get("entity_id") or "?"
    attrs = state.get("attributes") or {}
    name = attrs.get("friendly_name") or eid
    lines = [
        f"entity_id: {eid}",
        f"name: {name}",
        f"state: {state.get('state')}",
        f"domain: {domain_of(str(eid))}",
    ]
    if args.get("include_timestamps"):
        if state.get("last_changed"):
            lines.append(f"last_changed: {state['last_changed']}")
        if state.get("last_updated"):
            lines.append(f"last_updated: {state['last_updated']}")
    state_val = str(state.get("state") or "").lower()
    if state_val in {"unavailable", "unknown"}:
        lines.append("note: entity is unavailable — check device, integration, or logs before calling services")

    skip = {"friendly_name", "attribution"}
    if not args.get("include_capabilities"):
        skip.add("supported_features")
    interesting = {k: v for k, v in attrs.items() if k not in skip}
    full = bool(args.get("full_attributes"))
    if interesting:
        items = list(interesting.items()) if full else list(interesting.items())[:32]
        if full:
            lines.append("attributes:")
            lines.append(json.dumps(dict(items), ensure_ascii=False, indent=2, default=str))
        else:
            lines.append("attributes: " + ", ".join(f"{k}={v!r}" for k, v in items))
        if not full and len(interesting) > 32:
            lines.append(f"… {len(interesting) - 32} more attributes — use full_attributes=true")

    if args.get("include_capabilities"):
        caps = decode_capabilities(domain_of(str(eid)), attrs)
        if caps:
            lines.append("capabilities: " + "; ".join(caps))
    return "\n".join(lines)


def summarize_service_fields(fields: Any) -> str:
    if not isinstance(fields, dict):
        return ""
    parts: list[str] = []
    for key in sorted(fields.keys())[:12]:
        parts.append(str(key))
    if len(fields) > 12:
        parts.append("…")
    return ", ".join(parts)


def format_services_index(services: dict, domain: str | None = None, *, max_domains: int = 24) -> str:
    if not isinstance(services, dict) or not services:
        return "No services."
    doms = sorted(services.keys())
    if domain:
        doms = [d for d in doms if d == domain.strip().lower()]
        if not doms:
            return f"No services for domain '{domain}'."
    lines: list[str] = []
    shown = 0
    for dom in doms:
        block = services.get(dom) or {}
        if not isinstance(block, dict):
            continue
        for svc_name in sorted(block.keys()):
            fields = summarize_service_fields(block[svc_name])
            line = f"{dom}.{svc_name}"
            if fields:
                line += f" ({fields})"
            lines.append(line)
        shown += 1
        if shown >= max_domains and not domain:
            remaining = len(doms) - shown
            if remaining > 0:
                lines.append(f"… {remaining} more domains — pass domain= to narrow")
            break
    if not lines:
        return "No services."
    return "\n".join(lines)


def render_ha_agent_prompt(
    template: str,
    tool_names: list[str],
    *,
    compact: bool = False,
) -> str:
    default = COMPACT_HA_AGENT_PROMPT if compact else DEFAULT_HA_AGENT_PROMPT
    text = (template or "").strip() or default
    names = sorted(tool_names)
    if compact and len(names) > 12:
        joined = ", ".join(names[:12]) + f", … ({len(names)} tools total)"
    else:
        joined = ", ".join(names)
    if "{tools}" in text:
        return text.replace("{tools}", joined)
    return f"{text}\n\nTools: {joined}."


def index_areas(areas: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for row in areas:
        if not isinstance(row, dict):
            continue
        area_id = str(row.get("area_id") or row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if area_id:
            by_id[area_id] = name or area_id
        if name:
            by_name[name.lower()] = area_id
    return by_id, by_name


def index_devices(devices: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for row in devices:
        if not isinstance(row, dict):
            continue
        device_id = str(row.get("id") or "").strip()
        name = str(row.get("name_by_user") or row.get("name") or "").strip()
        if device_id:
            by_id[device_id] = name or device_id
        if name:
            by_name[name.lower()] = device_id
    return by_id, by_name


def registry_by_entity_id(entries: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in entries:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("entity_id") or "").strip()
        if eid:
            out[eid] = row
    return out


def resolve_area_id(
    area_names: dict[str, str],
    *,
    area_id: str | None = None,
    area_name: str | None = None,
) -> str | None:
    raw_id = (area_id or "").strip()
    if raw_id:
        return raw_id
    name = (area_name or "").strip().lower()
    if name and name in area_names:
        return area_names[name]
    return None


def index_labels(labels: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for row in labels:
        if not isinstance(row, dict):
            continue
        label_id = str(row.get("label_id") or row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if label_id:
            by_id[label_id] = name or label_id
        if name:
            by_name[name.lower()] = label_id
    return by_id, by_name


def resolve_label_ids(
    label_names: dict[str, str],
    labels: Any,
) -> list[str] | None:
    if labels is None:
        return None
    if not isinstance(labels, list):
        return None
    resolved: list[str] = []
    for item in labels:
        raw = str(item or "").strip()
        if not raw:
            continue
        lower = raw.lower()
        if lower in label_names:
            resolved.append(label_names[lower])
        else:
            resolved.append(raw)
    return resolved


def index_floors(floors: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for row in floors:
        if not isinstance(row, dict):
            continue
        floor_id = str(row.get("floor_id") or row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if floor_id:
            by_id[floor_id] = name or floor_id
        if name:
            by_name[name.lower()] = floor_id
    return by_id, by_name


def resolve_floor_id(
    floor_names: dict[str, str],
    *,
    floor_id: str | None = None,
    floor_name: str | None = None,
) -> str | None:
    raw_id = (floor_id or "").strip()
    if raw_id:
        return raw_id
    name = (floor_name or "").strip().lower()
    if name and name in floor_names:
        return floor_names[name]
    return None


def merge_entities(
    states: list[dict],
    registry: dict[str, dict],
    area_labels: dict[str, str],
    device_labels: dict[str, str],
) -> list[dict]:
    state_map = {
        str(st.get("entity_id") or ""): st for st in states if isinstance(st, dict) and st.get("entity_id")
    }
    ids = sorted(set(state_map) | set(registry))
    rows: list[dict] = []
    for eid in ids:
        st = state_map.get(eid, {})
        reg = registry.get(eid, {})
        attrs = st.get("attributes") or {}
        area_id = str(reg.get("area_id") or "") or None
        device_id = str(reg.get("device_id") or "") or None
        rows.append(
            {
                "entity_id": eid,
                "domain": domain_of(eid),
                "state": st.get("state"),
                "attributes": attrs,
                "registry_name": reg.get("name") or reg.get("original_name") or "",
                "area_id": area_id,
                "area_name": area_labels.get(area_id or "", "") if area_id else "",
                "device_id": device_id,
                "device_name": device_labels.get(device_id or "", "") if device_id else "",
                "disabled_by": reg.get("disabled_by"),
                "hidden_by": reg.get("hidden_by"),
                "platform": reg.get("platform") or "",
            }
        )
    return rows


def filter_enriched(rows: list[dict], args: dict) -> list[dict]:
    domains = parse_domains(args.get("domain"))
    search = (args.get("search") or "").strip().lower()
    state_filter = (args.get("state_filter") or "").strip().lower()
    area_id = (args.get("area_id") or "").strip()
    area_name = (args.get("area_name") or "").strip().lower()
    device_id = (args.get("device_id") or "").strip()
    include_disabled = bool(args.get("include_disabled"))
    include_hidden = bool(args.get("include_hidden"))

    filtered: list[dict] = []
    for row in rows:
        eid = str(row.get("entity_id") or "")
        if not entity_matches_domains(eid, domains):
            continue
        if area_id and str(row.get("area_id") or "") != area_id:
            continue
        if area_name and area_name not in str(row.get("area_name") or "").lower():
            continue
        if device_id and str(row.get("device_id") or "") != device_id:
            continue
        if not include_disabled and row.get("disabled_by"):
            continue
        if not include_hidden and row.get("hidden_by"):
            continue
        state_val = str(row.get("state") or "").lower()
        if state_filter and state_filter != state_val:
            continue
        label = " ".join(
            p
            for p in (
                eid,
                str(row.get("registry_name") or ""),
                str((row.get("attributes") or {}).get("friendly_name") or ""),
                str(row.get("area_name") or ""),
                str(row.get("device_name") or ""),
            )
            if p
        ).lower()
        if search and search not in label:
            continue
        filtered.append(row)
    return filtered


def sort_enriched(rows: list[dict], sort_key: str | None) -> list[dict]:
    key = (sort_key or "entity_id").strip().lower()
    if key == "name":
        return sorted(
            rows,
            key=lambda r: str(r.get("registry_name") or (r.get("attributes") or {}).get("friendly_name") or r.get("entity_id") or "").lower(),
        )
    if key == "state":
        return sorted(rows, key=lambda r: str(r.get("state") or "").lower())
    return sorted(rows, key=lambda r: str(r.get("entity_id") or "").lower())


def format_enriched_row(row: dict) -> str:
    name = str(row.get("registry_name") or (row.get("attributes") or {}).get("friendly_name") or "")
    state_val = row.get("state") if row.get("state") is not None else "?"
    area = str(row.get("area_name") or row.get("area_id") or "")
    device = str(row.get("device_name") or row.get("device_id") or "")[:24]
    disabled = "yes" if row.get("disabled_by") else ""
    return f"{row.get('entity_id')}|{name}|{state_val}|{area}|{device}|{disabled}"


def format_enriched_list(rows: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not rows and total == 0:
        return "No matching entities."
    lines = ["entity_id|name|state|area|device|disabled"]
    lines.extend(format_enriched_row(row) for row in rows)
    end = offset + len(rows)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def filter_registry_entries(entries: list[dict], args: dict) -> list[dict]:
    domains = parse_domains(args.get("domain"))
    search = (args.get("search") or "").strip().lower()
    area_id = (args.get("area_id") or "").strip()
    include_disabled = bool(args.get("include_disabled"))
    rows: list[dict] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("entity_id") or "")
        if not entity_matches_domains(eid, domains):
            continue
        if area_id and str(row.get("area_id") or "") != area_id:
            continue
        if not include_disabled and row.get("disabled_by"):
            continue
        label = " ".join(
            p
            for p in (eid, str(row.get("name") or ""), str(row.get("original_name") or ""))
            if p
        ).lower()
        if search and search not in label:
            continue
        rows.append(row)
    return sorted(rows, key=lambda r: str(r.get("entity_id") or ""))


def format_registry_entry(row: dict, area_labels: dict[str, str], device_labels: dict[str, str]) -> str:
    eid = row.get("entity_id") or "?"
    area_id = str(row.get("area_id") or "")
    device_id = str(row.get("device_id") or "")
    lines = [
        f"entity_id: {eid}",
        f"name: {row.get('name') or row.get('original_name') or ''}",
        f"platform: {row.get('platform') or '?'}",
        f"area: {area_labels.get(area_id, area_id) or '(none)'}",
        f"device: {device_labels.get(device_id, device_id) or '(none)'}",
        f"disabled_by: {row.get('disabled_by') or '(enabled)'}",
        f"hidden_by: {row.get('hidden_by') or '(visible)'}",
    ]
    labels = row.get("labels")
    if labels:
        lines.append(f"labels: {', '.join(sorted(labels)) if isinstance(labels, (list, set)) else labels}")
    return "\n".join(lines)


def format_registry_list(rows: list[dict], area_labels: dict[str, str]) -> str:
    if not rows:
        return "No matching registry entries."
    lines = ["entity_id|name|area|platform|disabled"]
    for row in rows[:120]:
        eid = row.get("entity_id") or "?"
        area_id = str(row.get("area_id") or "")
        area = area_labels.get(area_id, area_id) or ""
        lines.append(
            f"{eid}|{row.get('name') or row.get('original_name') or ''}|{area}|{row.get('platform') or ''}|{'yes' if row.get('disabled_by') else ''}"
        )
    if len(rows) > 120:
        lines.append(f"… showing 120 of {len(rows)} — narrow with search/domain/area_id")
    return "\n".join(lines)


def format_area_list(areas: list[dict]) -> str:
    if not areas:
        return "No areas."
    lines = ["area_id|name|icon"]
    for row in sorted(areas, key=lambda r: str(r.get("name") or "")):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{row.get('area_id') or row.get('id') or '?'}|{row.get('name') or ''}|{row.get('icon') or ''}"
        )
    return "\n".join(lines)


def format_label_list(labels: list[dict]) -> str:
    if not labels:
        return "No labels."
    lines = ["label_id|name|color|icon"]
    for row in sorted(labels, key=lambda r: str(r.get("name") or "")):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{row.get('label_id') or row.get('id') or '?'}|{row.get('name') or ''}|{row.get('color') or ''}|{row.get('icon') or ''}"
        )
    return "\n".join(lines)


def format_device_list(devices: list[dict], area_labels: dict[str, str]) -> str:
    if not devices:
        return "No devices."
    lines = ["device_id|name|area|manufacturer|model"]
    for row in sorted(devices, key=lambda r: str(r.get("name") or r.get("name_by_user") or "")):
        if not isinstance(row, dict):
            continue
        area_id = str(row.get("area_id") or "")
        name = row.get("name_by_user") or row.get("name") or ""
        lines.append(
            f"{row.get('id') or '?'}|{name}|{area_labels.get(area_id, area_id) or ''}|{row.get('manufacturer') or ''}|{row.get('model') or ''}"
        )
        if len(lines) > 121:
            lines.append("… truncated")
            break
    return "\n".join(lines)


def format_device_detail(device: dict, area_labels: dict[str, str], entities: list[dict] | None = None) -> str:
    area_id = str(device.get("area_id") or "")
    lines = [
        f"device_id: {device.get('id') or '?'}",
        f"name: {device.get('name_by_user') or device.get('name') or ''}",
        f"manufacturer: {device.get('manufacturer') or ''}",
        f"model: {device.get('model') or ''}",
        f"area: {area_labels.get(area_id, area_id) or '(none)'}",
        f"disabled_by: {device.get('disabled_by') or '(enabled)'}",
    ]
    if entities:
        eids = [str(e.get("entity_id") or "") for e in entities if e.get("entity_id")]
        if eids:
            preview = ", ".join(sorted(eids)[:12])
            if len(eids) > 12:
                preview += f", … (+{len(eids) - 12})"
            lines.append(f"entities: {preview}")
    return "\n".join(lines)


def build_entity_update_payload(
    args: dict,
    area_name_index: dict[str, str],
    label_name_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.get("name") is not None:
        payload["name"] = args.get("name")
    if args.get("new_entity_id"):
        payload["new_entity_id"] = args["new_entity_id"]
    if args.get("icon") is not None:
        payload["icon"] = args.get("icon")
    if args.get("labels") is not None:
        resolved = resolve_label_ids(label_name_index or {}, args.get("labels"))
        payload["labels"] = resolved if resolved is not None else args.get("labels")
    area_id = resolve_area_id(
        area_name_index,
        area_id=args.get("area_id"),
        area_name=args.get("area_name"),
    )
    if args.get("area_id") is not None or args.get("area_name") is not None:
        payload["area_id"] = area_id
    if args.get("disabled") is True:
        payload["disabled_by"] = "user"
    elif args.get("disabled") is False:
        payload["disabled_by"] = None
    if args.get("hidden") is True:
        payload["hidden_by"] = "user"
    elif args.get("hidden") is False:
        payload["hidden_by"] = None
    return payload


def build_area_create_payload(
    args: dict,
    label_name_index: dict[str, str] | None = None,
    floor_name_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": (args.get("name") or "").strip()}
    if not payload["name"]:
        return {}
    for key in ("icon", "picture"):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    floor_id = resolve_floor_id(
        floor_name_index or {},
        floor_id=args.get("floor_id"),
        floor_name=args.get("floor_name"),
    )
    if args.get("floor_id") is not None or args.get("floor_name") is not None:
        payload["floor_id"] = floor_id
    if args.get("labels") is not None:
        resolved = resolve_label_ids(label_name_index or {}, args.get("labels"))
        payload["labels"] = resolved if resolved is not None else args.get("labels")
    return payload


def build_area_update_payload(
    args: dict,
    label_name_index: dict[str, str] | None = None,
    floor_name_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    area_id = (args.get("area_id") or "").strip()
    if not area_id:
        return {}
    payload["area_id"] = area_id
    for key in ("name", "icon", "picture"):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    floor_id = resolve_floor_id(
        floor_name_index or {},
        floor_id=args.get("floor_id"),
        floor_name=args.get("floor_name"),
    )
    if args.get("floor_id") is not None or args.get("floor_name") is not None:
        payload["floor_id"] = floor_id
    if args.get("labels") is not None:
        resolved = resolve_label_ids(label_name_index or {}, args.get("labels"))
        payload["labels"] = resolved if resolved is not None else args.get("labels")
    return payload


def build_device_update_payload(
    args: dict,
    area_name_index: dict[str, str],
    label_name_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    device_id = (args.get("device_id") or "").strip()
    if not device_id:
        return {}
    payload["device_id"] = device_id
    if args.get("name_by_user") is not None:
        payload["name_by_user"] = args.get("name_by_user")
    area_id = resolve_area_id(
        area_name_index,
        area_id=args.get("area_id"),
        area_name=args.get("area_name"),
    )
    if args.get("area_id") is not None or args.get("area_name") is not None:
        payload["area_id"] = area_id
    if args.get("labels") is not None:
        resolved = resolve_label_ids(label_name_index or {}, args.get("labels"))
        payload["labels"] = resolved if resolved is not None else args.get("labels")
    if args.get("disabled") is True:
        payload["disabled_by"] = "user"
    elif args.get("disabled") is False:
        payload["disabled_by"] = None
    return payload


def build_label_create_payload(args: dict) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": (args.get("name") or "").strip()}
    if not payload["name"]:
        return {}
    for key in ("color", "description", "icon"):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    return payload


def build_label_update_payload(args: dict) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    label_id = (args.get("label_id") or "").strip()
    if not label_id:
        return {}
    payload["label_id"] = label_id
    for key in ("name", "color", "description", "icon"):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    return payload


def build_floor_create_payload(args: dict) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": (args.get("name") or "").strip()}
    if not payload["name"]:
        return {}
    for key in ("icon",):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    if args.get("level") is not None:
        try:
            payload["level"] = int(args.get("level"))
        except (TypeError, ValueError):
            payload["level"] = args.get("level")
    return payload


def build_floor_update_payload(args: dict) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    floor_id = (args.get("floor_id") or "").strip()
    if not floor_id:
        return {}
    payload["floor_id"] = floor_id
    for key in ("name", "icon"):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    if args.get("level") is not None:
        try:
            payload["level"] = int(args.get("level"))
        except (TypeError, ValueError):
            payload["level"] = args.get("level")
    return payload


def format_floor_list(floors: list[dict]) -> str:
    if not floors:
        return "No floors."
    lines = ["floor_id|name|level|icon"]
    for row in sorted(floors, key=lambda r: str(r.get("name") or "")):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{row.get('floor_id') or row.get('id') or '?'}|{row.get('name') or ''}|{row.get('level') if row.get('level') is not None else ''}|{row.get('icon') or ''}"
        )
    return "\n".join(lines)


def format_automation_row(st: dict) -> str:
    attrs = st.get("attributes") or {}
    name = str(attrs.get("friendly_name") or st.get("entity_id") or "")
    mode = str(attrs.get("mode") or "")
    last = str(attrs.get("last_triggered") or "")
    return f"{st.get('entity_id')}|{name}|{st.get('state')}|{mode}|{last}"


def format_automation_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching automations."
    lines = ["entity_id|name|state|mode|last_triggered"]
    lines.extend(format_automation_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def format_script_row(st: dict) -> str:
    attrs = st.get("attributes") or {}
    name = str(attrs.get("friendly_name") or st.get("entity_id") or "")
    last = str(attrs.get("last_triggered") or "")
    return f"{st.get('entity_id')}|{name}|{st.get('state')}|{last}"


def format_script_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching scripts."
    lines = ["entity_id|name|state|last_triggered"]
    lines.extend(format_script_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def format_scene_row(st: dict) -> str:
    attrs = st.get("attributes") or {}
    name = str(attrs.get("friendly_name") or st.get("entity_id") or "")
    entities = attrs.get("entity_id") or []
    count = len(entities) if isinstance(entities, list) else 0
    return f"{st.get('entity_id')}|{name}|{count} entities"


def format_scene_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching scenes."
    lines = ["entity_id|name|entities"]
    lines.extend(format_scene_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def format_automation_detail(state: dict) -> str:
    body = format_state_detail(
        state,
        {"include_timestamps": True, "full_attributes": False, "include_capabilities": False},
    )
    attrs = state.get("attributes") or {}
    extra: list[str] = []
    config_id = config_id_from_state(state)
    if config_id:
        extra.append(f"id: {config_id}")
    for key in ("mode", "current", "max", "last_triggered"):
        if attrs.get(key) is not None:
            extra.append(f"{key}: {attrs.get(key)}")
    if extra:
        body += "\nautomation: " + "; ".join(extra)
    return body


def config_id_from_state(state: dict) -> str:
    attrs = state.get("attributes") or {}
    return str(attrs.get("id") or "").strip()


def _summarize_automation_block(block: Any, *, max_len: int = 140) -> str:
    if isinstance(block, str):
        text = block.strip()
    elif isinstance(block, dict):
        parts: list[str] = []
        for key in ("platform", "service", "entity_id", "device_id", "area_id", "type", "alias"):
            val = block.get(key)
            if val not in (None, "", []):
                parts.append(f"{key}={val}")
        if not parts:
            parts.append(json.dumps(block, ensure_ascii=False, default=str)[: max_len - 8])
        text = " ".join(parts)
    else:
        text = str(block)
    text = " ".join(text.split())
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _automation_section(config: dict, *keys: str) -> list[Any]:
    for key in keys:
        val = config.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            return val
        return [val]
    return []


def format_automation_config(config: dict | None) -> str:
    if not config or not isinstance(config, dict):
        return ""
    lines = ["config:"]
    alias = config.get("alias") or config.get("id")
    if alias:
        lines.append(f"alias: {alias}")
    if config.get("description"):
        lines.append(f"description: {config['description']}")
    mode = config.get("mode")
    if mode:
        lines.append(f"mode: {mode}")

    triggers = _automation_section(config, "triggers", "trigger")
    lines.append(f"triggers ({len(triggers)}):")
    for idx, block in enumerate(triggers[:8], start=1):
        lines.append(f"  {idx}. {_summarize_automation_block(block)}")
    if len(triggers) > 8:
        lines.append(f"  … +{len(triggers) - 8} more")

    conditions = _automation_section(config, "conditions", "condition")
    if conditions:
        lines.append(f"conditions ({len(conditions)}):")
        for idx, block in enumerate(conditions[:4], start=1):
            lines.append(f"  {idx}. {_summarize_automation_block(block)}")
        if len(conditions) > 4:
            lines.append(f"  … +{len(conditions) - 4} more")

    actions = _automation_section(config, "actions", "action")
    lines.append(f"actions ({len(actions)}):")
    for idx, block in enumerate(actions[:10], start=1):
        lines.append(f"  {idx}. {_summarize_automation_block(block)}")
    if len(actions) > 10:
        lines.append(f"  … +{len(actions) - 10} more")
    return "\n".join(lines)


def resolve_config_entity(
    states: list[dict],
    domain: str,
    *,
    entity_id: str = "",
    search: str = "",
) -> tuple[str, str, dict] | str:
    """Resolve entity_id + config id for automation/script/scene delete."""
    eid = (entity_id or "").strip()
    query = (search or "").strip()
    if eid and not eid.startswith(f"{domain}."):
        return f"Error: entity_id must be {domain}.*"
    if not eid and query:
        filtered = filter_states(states, {"domain": domain, "search": query})
        if not filtered:
            return f"Error: no {domain} matching {query!r}"
        if len(filtered) > 1:
            ids = ", ".join(str(s.get("entity_id") or "") for s in filtered[:5])
            return f"Error: multiple matches ({ids}); pass entity_id"
        eid = str(filtered[0].get("entity_id") or "")
    if not eid:
        return "Error: entity_id or search is required"
    state = next((s for s in states if str(s.get("entity_id") or "") == eid), None)
    if not state:
        return f"Error: {eid} not found"
    config_id = config_id_from_state(state) or eid.split(".", 1)[-1]
    return eid, config_id, state


_STATISTICS_PERIODS = frozenset({"5minute", "hour", "day", "week", "month"})


def normalize_statistics_period(raw: Any) -> str:
    period = str(raw or "hour").strip().lower()
    return period if period in _STATISTICS_PERIODS else "hour"


def normalize_config_entries(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def filter_config_entries(entries: list[dict], args: dict, *, limit: int = 80) -> list[dict]:
    domain = str(args.get("domain") or "").strip().lower()
    search = str(args.get("search") or "").strip().lower()
    rows: list[dict] = []
    for row in entries:
        row_domain = str(row.get("domain") or "").lower()
        if domain and row_domain != domain:
            continue
        label = " ".join(
            str(row.get(key) or "")
            for key in ("entry_id", "domain", "title", "state", "source")
        ).lower()
        if search and search not in label:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return sorted(rows, key=lambda r: (str(r.get("domain") or ""), str(r.get("title") or "")))


def format_config_entry_list(entries: list[dict]) -> str:
    if not entries:
        return "No matching config entries."
    lines = ["entry_id|domain|title|state|source"]
    for row in entries:
        lines.append(
            f"{row.get('entry_id') or '?'}|{row.get('domain') or ''}|{row.get('title') or ''}|{row.get('state') or ''}|{row.get('source') or ''}"
        )
    return "\n".join(lines)


def format_config_entry_detail(entry: dict) -> str:
    lines = [
        f"entry_id: {entry.get('entry_id') or '?'}",
        f"domain: {entry.get('domain') or '?'}",
        f"title: {entry.get('title') or ''}",
        f"state: {entry.get('state') or '?'}",
        f"source: {entry.get('source') or ''}",
    ]
    if entry.get("reason"):
        lines.append(f"reason: {entry.get('reason')}")
    if entry.get("disabled_by"):
        lines.append(f"disabled_by: {entry.get('disabled_by')}")
    if entry.get("pref_disable_new_entities") is not None:
        lines.append(f"pref_disable_new_entities: {entry.get('pref_disable_new_entities')}")
    return "\n".join(lines)


def filter_statistic_ids(rows: list[Any], args: dict, *, limit: int = 120) -> list[str]:
    search = str(args.get("search") or "").strip().lower()
    out: list[str] = []
    for row in rows:
        sid = ""
        if isinstance(row, dict):
            sid = str(row.get("statistic_id") or row.get("id") or "")
        else:
            sid = str(row or "")
        if not sid:
            continue
        if search and search not in sid.lower():
            continue
        out.append(sid)
        if len(out) >= limit:
            break
    return sorted(out)


def format_statistic_id_list(ids: list[str]) -> str:
    if not ids:
        return "No matching statistic ids."
    lines = ["statistic_id"]
    lines.extend(ids)
    if len(ids) >= 120:
        lines.append("… truncated")
    return "\n".join(lines)


def format_statistics_response(payload: Any, statistic_ids: list[str], *, max_rows: int = 24) -> str:
    if not isinstance(payload, dict) or not payload:
        return "No statistics for the requested period."
    lines: list[str] = []
    for sid in statistic_ids:
        block = payload.get(sid)
        if not isinstance(block, list) or not block:
            lines.append(f"{sid}: (no data — try ha_list_statistic_ids or a longer period)")
            continue
        lines.append(f"{sid} ({len(block)} points, showing last {min(len(block), max_rows)}):")
        for row in block[-max_rows:]:
            if not isinstance(row, dict):
                continue
            start = row.get("start") or row.get("start_time") or "?"
            parts = []
            for key in ("mean", "min", "max", "sum", "state"):
                if row.get(key) is not None:
                    parts.append(f"{key}={row.get(key)}")
            lines.append(f"  {start}: " + (", ".join(parts) if parts else json.dumps(row, default=str)[:120]))
    return "\n".join(lines)


def format_group_row(st: dict) -> str:
    attrs = st.get("attributes") or {}
    name = str(attrs.get("friendly_name") or st.get("entity_id") or "")
    members = attrs.get("entity_id") or []
    count = len(members) if isinstance(members, list) else 0
    return f"{st.get('entity_id')}|{name}|{count} members"


def format_group_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching groups."
    lines = ["entity_id|name|members"]
    lines.extend(format_group_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def format_zone_row(st: dict) -> str:
    attrs = st.get("attributes") or {}
    name = str(attrs.get("friendly_name") or st.get("entity_id") or "")
    radius = attrs.get("radius")
    passive = attrs.get("passive")
    return f"{st.get('entity_id')}|{name}|{st.get('state')}|radius={radius}|passive={passive}"


def format_zone_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching zones."
    lines = ["entity_id|name|state|radius|passive"]
    lines.extend(format_zone_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def format_person_row(st: dict) -> str:
    attrs = st.get("attributes") or {}
    name = str(attrs.get("friendly_name") or st.get("entity_id") or "")
    user_id = str(attrs.get("user_id") or "")
    devices = attrs.get("device_trackers") or attrs.get("source") or []
    count = len(devices) if isinstance(devices, list) else 0
    return f"{st.get('entity_id')}|{name}|{st.get('state')}|trackers={count}|user_id={user_id}"


def format_person_list(states: list[dict], *, total: int, offset: int, limit: int) -> str:
    if not states and total == 0:
        return "No matching persons."
    lines = ["entity_id|name|state|trackers|user_id"]
    lines.extend(format_person_row(st) for st in states)
    end = offset + len(states)
    footer = f"showing {offset + 1}-{end} of {total}"
    if end < total:
        footer += f" — use offset={end} for more"
    lines.append(footer)
    return "\n".join(lines)


def can_set_state(entity_id: str) -> bool:
    return domain_of(entity_id) in _STATE_SET_DOMAINS


def parse_entity_id_args(args: dict, *, max_ids: int = 8) -> list[str]:
    raw_ids = args.get("entity_ids")
    ids: list[str] = []
    if isinstance(raw_ids, list):
        ids.extend(str(item or "").strip() for item in raw_ids if str(item or "").strip())
    single = str(args.get("entity_id") or "").strip()
    if single:
        ids.append(single)
    if not ids:
        csv = str(args.get("filter_entity_id") or "").strip()
        if csv:
            ids.extend(part.strip() for part in csv.split(",") if part.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for eid in ids:
        key = eid.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(eid)
    return deduped[:max_ids]


def clamp_hours(raw: Any, *, default: int = 24, max_hours: int = 168) -> int:
    try:
        value = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, max_hours))


def format_history_rows(entity_id: str, rows: list[dict], *, max_rows: int = 40) -> list[str]:
    lines: list[str] = []
    if not rows:
        lines.append(f"{entity_id}: (no history)")
        return lines
    lines.append(f"{entity_id} ({len(rows)} states, showing last {min(len(rows), max_rows)}):")
    for row in rows[-max_rows:]:
        if not isinstance(row, dict):
            continue
        state_val = row.get("state")
        when = row.get("last_changed") or row.get("last_updated") or "?"
        lines.append(f"  {when} → {state_val}")
    return lines


def format_history_response(payload: Any, entity_ids: list[str], *, max_rows: int = 40) -> str:
    if not isinstance(payload, list) or not payload:
        return "No history entries."
    lines: list[str] = []
    for idx, block in enumerate(payload):
        eid = entity_ids[idx] if idx < len(entity_ids) else f"entity_{idx + 1}"
        rows = block if isinstance(block, list) else []
        lines.extend(format_history_rows(eid, rows, max_rows=max_rows))
    return "\n".join(lines)


def format_logbook_entries(entries: list[dict], *, max_rows: int = 60) -> str:
    if not entries:
        return "No logbook entries."
    lines = ["when|entity|message"]
    for row in entries[:max_rows]:
        if not isinstance(row, dict):
            continue
        when = str(row.get("when") or row.get("timestamp") or "")
        eid = str(row.get("entity_id") or "")
        message = str(row.get("message") or row.get("name") or "")
        lines.append(f"{when}|{eid}|{message}")
    if len(entries) > max_rows:
        lines.append(f"… showing {max_rows} of {len(entries)}")
    return "\n".join(lines)


def filter_entity_sources(sources: dict[str, dict], args: dict, *, limit: int = 80) -> list[tuple[str, dict]]:
    entity_id = str(args.get("entity_id") or "").strip().lower()
    domain = str(args.get("domain") or "").strip().lower()
    search = str(args.get("search") or "").strip().lower()
    rows: list[tuple[str, dict]] = []
    for eid, info in sorted(sources.items()):
        if not isinstance(info, dict):
            continue
        if entity_id and eid.lower() != entity_id:
            continue
        src_domain = str(info.get("domain") or info.get("platform") or "").lower()
        if domain and src_domain != domain and not eid.lower().startswith(domain + "."):
            continue
        label = f"{eid} {src_domain}".lower()
        if search and search not in label:
            continue
        rows.append((eid, info))
        if len(rows) >= limit:
            break
    return rows


def format_entity_source_list(rows: list[tuple[str, dict]]) -> str:
    if not rows:
        return "No matching entity sources."
    lines = ["entity_id|source"]
    for eid, info in rows:
        src = str(info.get("domain") or info.get("platform") or info.get("source") or "?")
        config_entry = info.get("config_entry")
        if config_entry:
            src = f"{src} (entry={config_entry})"
        lines.append(f"{eid}|{src}")
    return "\n".join(lines)


def filter_exposed_entities(data: dict[str, dict], args: dict, *, limit: int = 120) -> list[tuple[str, list[str]]]:
    assistant = str(args.get("assistant") or "").strip()
    search = str(args.get("search") or "").strip().lower()
    rows: list[tuple[str, list[str]]] = []
    for eid, exposed_to in sorted(data.items()):
        if not isinstance(exposed_to, dict):
            continue
        assistants = sorted(key for key, enabled in exposed_to.items() if enabled)
        if assistant and assistant not in assistants:
            continue
        if search and search not in eid.lower():
            continue
        rows.append((eid, assistants))
        if len(rows) >= limit:
            break
    return rows


def format_exposed_entity_list(rows: list[tuple[str, list[str]]]) -> str:
    if not rows:
        return "No exposed entities."
    lines = ["entity_id|assistants"]
    for eid, assistants in rows:
        lines.append(f"{eid}|{','.join(assistants)}")
    return "\n".join(lines)


def build_expose_entity_payload(args: dict) -> dict[str, Any]:
    entity_ids = parse_entity_id_args(args, max_ids=20)
    if not entity_ids:
        return {}
    assistants = args.get("assistants")
    if isinstance(assistants, list) and assistants:
        assistant_list = [str(a).strip() for a in assistants if str(a).strip()]
    else:
        assistant_list = ["conversation"]
    if args.get("should_expose") is None:
        return {}
    return {
        "entity_ids": entity_ids,
        "assistants": assistant_list,
        "should_expose": bool(args.get("should_expose")),
    }


def entity_error_hint(tool_name: str, message: str) -> str | None:
    lower = message.lower()
    if tool_name == "ha_set_state" and "not allowed" in lower:
        return "Use ha_call_service for lights, switches, climate, and other device entities."
    if tool_name in {"ha_get_history", "ha_get_logbook"} and "filter_entity_id" in lower:
        return "Pass entity_id or entity_ids."
    if tool_name == "ha_get_statistics" and ("recorder" in lower or "statistic" in lower):
        return "Use ha_list_statistic_ids to find valid statistic_id values."
    if tool_name == "ha_get_config_entry" and ("not found" in lower or "404" in lower):
        return "Use ha_list_config_entries to find entry_id."
    if tool_name in {"ha_delete_automation", "ha_delete_script", "ha_delete_scene"}:
        if "405" in lower:
            return "Update Home Assistant Supervisor or delete from Settings in the HA UI."
        if "automations.yaml" in lower or "scripts.yaml" in lower or "scenes.yaml" in lower:
            return "This item may live in a package or custom YAML file — use ha_list_files and ha_read_file."
    if "not found" in lower or "404" in lower:
        return "Use ha_list_entities or ha_list_entity_registry to find the correct entity_id."
    if "area" in lower and "unknown" in lower:
        return "Use ha_list_areas to resolve area_id from a room name."
    if "label" in lower and ("unknown" in lower or "invalid" in lower):
        return "Use ha_list_labels to resolve label_id from a label name."
    return None
