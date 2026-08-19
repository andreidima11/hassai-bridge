"""Pure Home Assistant entity helpers (testable without a live instance)."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_HA_AGENT_PROMPT = """You are the Home Assistant administrator copilot. Available tools: {tools}.

Chain tools until the job is done — do not stop after a single lookup.

Entities (live state via REST):
- Find: ha_list_entities (search, domain, offset) → ha_get_state on the exact entity_id
- Act: ha_list_services(domain=…) for valid services/fields → ha_call_service → ha_get_state to verify
- List includes all domains by default; narrow with domain= or search=
- state.attributes.area_id is often empty — area lives in entity registry (future tools)
- If state is unavailable or unknown, diagnose before calling services
- entity_id in ha_call_service can be a list via data.entity_id for multiple targets

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
