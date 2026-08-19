"""Pure Home Assistant entity helpers (testable without a live instance)."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_HA_AGENT_PROMPT = """You are the Home Assistant administrator copilot. Available tools: {tools}.

Chain tools until the job is done — do not stop after a single lookup.

Entities (live state via REST):
- Find: ha_list_entities (search, domain, area_name, offset; registry columns when available) → ha_get_state
- Registry metadata: ha_list_entity_registry / ha_get_entity_registry — names, areas, devices, disabled/hidden
- Rename/move/disable: ha_update_entity (confirm=true); resolve area with ha_list_areas
- Helpers only: ha_set_state for input_* / counter / timer — devices use ha_call_service
- Act: ha_list_services(domain=…) → ha_call_service → ha_get_state to verify
- area_id in registry, not state.attributes — use ha_list_areas for room names
- If state is unavailable or unknown, diagnose before calling services

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
Mutating tools need confirm=true when the user already asked you to make the change."""

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
})

HA_REGISTRY_MUTATING_TOOLS = frozenset({
    "ha_update_entity",
    "ha_set_state",
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


def filter_states(states: list[dict], args: dict) -> list[dict]:
    domain = (args.get("domain") or "").strip().lower()
    search = (args.get("search") or "").strip().lower()
    state_filter = (args.get("state_filter") or "").strip().lower()
    include_all = args.get("include_all_domains")
    if include_all is None:
        include_all = True if (domain or search) else True

    rows: list[dict] = []
    for st in states:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        if not eid:
            continue
        if domain and not eid.startswith(domain + "."):
            continue
        if not domain and not search and not include_all:
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


def render_ha_agent_prompt(template: str, tool_names: list[str]) -> str:
    text = (template or "").strip() or DEFAULT_HA_AGENT_PROMPT
    joined = ", ".join(sorted(tool_names))
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
    domain = (args.get("domain") or "").strip().lower()
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
        if domain and not eid.startswith(domain + "."):
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
    domain = (args.get("domain") or "").strip().lower()
    search = (args.get("search") or "").strip().lower()
    area_id = (args.get("area_id") or "").strip()
    include_disabled = bool(args.get("include_disabled"))
    rows: list[dict] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("entity_id") or "")
        if domain and not eid.startswith(domain + "."):
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
    lines = ["area_id|name"]
    for row in sorted(areas, key=lambda r: str(r.get("name") or "")):
        if not isinstance(row, dict):
            continue
        lines.append(f"{row.get('area_id') or row.get('id') or '?'}|{row.get('name') or ''}")
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


def build_entity_update_payload(args: dict, area_name_index: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.get("name") is not None:
        payload["name"] = args.get("name")
    if args.get("new_entity_id"):
        payload["new_entity_id"] = args["new_entity_id"]
    if args.get("icon") is not None:
        payload["icon"] = args.get("icon")
    if args.get("labels") is not None:
        payload["labels"] = args.get("labels")
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


def can_set_state(entity_id: str) -> bool:
    return domain_of(entity_id) in _STATE_SET_DOMAINS


def entity_error_hint(tool_name: str, message: str) -> str | None:
    lower = message.lower()
    if tool_name == "ha_set_state" and "not allowed" in lower:
        return "Use ha_call_service for lights, switches, climate, and other device entities."
    if "not found" in lower or "404" in lower:
        return "Use ha_list_entities or ha_list_entity_registry to find the correct entity_id."
    if "area" in lower and "unknown" in lower:
        return "Use ha_list_areas to resolve area_id from a room name."
    return None
