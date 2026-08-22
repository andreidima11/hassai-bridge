"""Per-category enable flags for Home Assistant agent tools (Settings UI)."""

from __future__ import annotations

from typing import Any

# Settings keys (ha_tools.<key>) — all default True when missing.
CATEGORY_KEYS: dict[str, str] = {
    "entities": "Read entities, states, history, services, statistics",
    "control": "Call services, set helpers, run scripts and scenes",
    "registry": "Mutate areas, labels, devices, floors, entity registry",
    "automations": "Create, edit, delete automations and scripts",
    "integrations": "List and reload config entries (not OAuth pairing)",
    "dashboards": "Lovelace dashboards, views, cards",
    "config_files": "List, read, write text YAML in /config",
    "diagnostics": "Logs, problems, config check, partial reload, jobs",
    "backups": "Supervisor backup list, create, restore",
    "addons": "Add-on start, stop, restart, list",
    "updates": "Check and install HA Core, OS, Supervisor, add-on updates",
    "restart": "Restart Home Assistant Core or reboot the host",
    "network": "Network info, ping, port checks",
    "upload": "Write binary files to /config, /media, /share",
    "zigbee": "ZHA permit/remove and Z-Wave heal (via integration services)",
}

DEFAULT_HA_TOOLS: dict[str, bool] = {k: True for k in CATEGORY_KEYS}

# Tool name → category (existing + new supervisor tools).
_TOOL_CATEGORIES: dict[str, str] = {
    # entities
    "ha_list_entities": "entities",
    "ha_get_state": "entities",
    "ha_list_services": "entities",
    "ha_list_entity_registry": "entities",
    "ha_get_entity_registry": "entities",
    "ha_list_areas": "entities",
    "ha_list_devices": "entities",
    "ha_get_device": "entities",
    "ha_list_labels": "entities",
    "ha_list_floors": "entities",
    "ha_get_history": "entities",
    "ha_get_logbook": "entities",
    "ha_get_entity_source": "entities",
    "ha_list_exposed_entities": "entities",
    "ha_list_automations": "entities",
    "ha_get_automation": "entities",
    "ha_list_scripts": "entities",
    "ha_list_scenes": "entities",
    "ha_list_config_entries": "entities",
    "ha_get_config_entry": "entities",
    "ha_list_statistic_ids": "entities",
    "ha_get_statistics": "entities",
    "ha_list_groups": "entities",
    "ha_list_zones": "entities",
    "ha_list_persons": "entities",
    "ha_system_info": "entities",
    # control
    "ha_call_service": "control",
    "ha_set_state": "control",
    "ha_trigger_automation": "control",
    "ha_run_script": "control",
    "ha_activate_scene": "control",
    # registry
    "ha_update_entity": "registry",
    "ha_create_area": "registry",
    "ha_update_area": "registry",
    "ha_create_label": "registry",
    "ha_update_label": "registry",
    "ha_update_device": "registry",
    "ha_expose_entity": "registry",
    "ha_create_floor": "registry",
    "ha_update_floor": "registry",
    "ha_delete_automation": "registry",
    "ha_delete_script": "registry",
    "ha_delete_scene": "registry",
    # automations
    "ha_create_automation": "automations",
    "ha_update_automation": "automations",
    "ha_create_script": "automations",
    "ha_update_script": "automations",
    # integrations
    "ha_reload_config_entry": "integrations",
    # dashboards
    "ha_list_dashboards": "dashboards",
    "ha_get_dashboard": "dashboards",
    "ha_create_dashboard": "dashboards",
    "ha_save_dashboard": "dashboards",
    "ha_upsert_view": "dashboards",
    "ha_upsert_section": "dashboards",
    "ha_upsert_card": "dashboards",
    "ha_delete_card": "dashboards",
    "ha_delete_view": "dashboards",
    "ha_update_dashboard": "dashboards",
    "ha_delete_dashboard": "dashboards",
    "ha_list_lovelace_resources": "dashboards",
    "ha_append_card_yaml": "dashboards",
    # config_files
    "ha_list_files": "config_files",
    "ha_read_file": "config_files",
    "ha_write_file": "config_files",
    # diagnostics
    "ha_get_logs": "diagnostics",
    "ha_list_problems": "diagnostics",
    "ha_apply_fix": "diagnostics",
    "ha_check_config": "diagnostics",
    "ha_reload": "diagnostics",
    "ha_get_job": "diagnostics",
    # backups
    "ha_list_backups": "backups",
    "ha_create_backup": "backups",
    "ha_restore_backup": "backups",
    # addons
    "ha_list_addons": "addons",
    "ha_get_addon": "addons",
    "ha_start_addon": "addons",
    "ha_stop_addon": "addons",
    "ha_restart_addon": "addons",
    # updates
    "ha_list_updates": "updates",
    "ha_update_core": "updates",
    "ha_update_addon": "updates",
    "ha_update_supervisor": "updates",
    "ha_update_os": "updates",
    # restart
    "ha_restart_core": "restart",
    "ha_reboot_host": "restart",
    # network
    "ha_network_info": "network",
    "ha_ping_host": "network",
    "ha_check_port": "network",
    # upload
    "ha_upload_file": "upload",
    # zigbee
    "ha_mesh_network": "zigbee",
}


def tool_category(name: str) -> str:
    return _TOOL_CATEGORIES.get(name, "entities")


def merged_ha_tools_config(cfg: dict | None) -> dict[str, bool]:
    raw = (cfg or {}).get("ha_tools") if isinstance((cfg or {}).get("ha_tools"), dict) else {}
    out = dict(DEFAULT_HA_TOOLS)
    for key in CATEGORY_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def enabled_categories(cfg: dict | None) -> set[str]:
    flags = merged_ha_tools_config(cfg)
    return {k for k, on in flags.items() if on}


def tool_enabled(name: str, cfg: dict | None) -> bool:
    cat = tool_category(name)
    return cat in enabled_categories(cfg)


def filter_tool_names(names: list[str], cfg: dict | None) -> list[str]:
    enabled = enabled_categories(cfg)
    return [n for n in names if tool_category(n) in enabled]


def register_tool_category(name: str, category: str) -> None:
    _TOOL_CATEGORIES[name] = category
