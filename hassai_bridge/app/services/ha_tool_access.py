"""Per-category enable flags for Home Assistant agent tools (Settings UI)."""

from __future__ import annotations

from typing import Any

# Settings keys (ha_tools.<key>) — all default True when missing.
CATEGORY_KEYS: dict[str, str] = {
    "entities": "Read entities, states, history, services, statistics",
    "control": "Call services, notifications, media players, run scripts and scenes",
    "registry": "Mutate areas, labels, devices, floors, entity registry",
    "automations": "Create/edit automations, scripts, scenes; list/get traces",
    "integrations": "List, reload, disable, remove, configure integrations (flows)",
    "calendar": "Calendars, events, todo lists, shopping list",
    "helpers": "Create, update, delete input_*, timer, counter, schedule helpers",
    "dashboards": "Lovelace dashboards, views, cards",
    "config_files": "List, read, write YAML/JSON/txt in /config",
    "custom_code": "Edit custom_components/*.py (preview diff, .bak backup; off by default)",
    "diagnostics": "Logs, problems, config check, reload, recorder purge",
    "backups": "Supervisor backup list, create, restore",
    "addons": "Add-on start, stop, restart, list",
    "updates": "Check and install HA Core, OS, Supervisor, add-on updates",
    "restart": "Restart Home Assistant Core or reboot the host",
    "network": "Network info, ping, port checks",
    "upload": "Write binary files to /config, /media, /share",
    "zigbee": "ZHA / Z-Wave / Matter / Thread / Bluetooth diagnostics and pairing",
    "hacs": "HACS repository list, install/update, remove",
}

DEFAULT_HA_TOOLS: dict[str, bool] = {k: True for k in CATEGORY_KEYS}
# Dangerous by default — enable explicitly in Settings → HA tools.
DEFAULT_HA_TOOLS["custom_code"] = False

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
    "ha_notify": "control",
    "ha_list_persistent_notifications": "control",
    "ha_create_persistent_notification": "control",
    "ha_dismiss_persistent_notification": "control",
    "ha_media_browse": "control",
    "ha_media_search": "control",
    "ha_media_play": "control",
    "ha_media_control": "control",
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
    "ha_get_scene": "automations",
    "ha_create_scene": "automations",
    "ha_update_scene": "automations",
    "ha_list_traces": "automations",
    "ha_get_trace": "automations",
    # integrations
    "ha_reload_config_entry": "integrations",
    "ha_delete_config_entry": "integrations",
    "ha_disable_config_entry": "integrations",
    "ha_update_config_entry": "integrations",
    "ha_list_integration_handlers": "integrations",
    "ha_start_config_flow": "integrations",
    "ha_continue_config_flow": "integrations",
    "ha_start_options_flow": "integrations",
    # calendar / todo
    "ha_list_calendars": "calendar",
    "ha_list_calendar_events": "calendar",
    "ha_create_calendar_event": "calendar",
    "ha_update_calendar_event": "calendar",
    "ha_delete_calendar_event": "calendar",
    "ha_list_todo_lists": "calendar",
    "ha_list_todo_items": "calendar",
    "ha_create_todo_list": "calendar",
    "ha_delete_todo_list": "calendar",
    "ha_clear_todo_list": "calendar",
    "ha_add_todo_item": "calendar",
    "ha_update_todo_item": "calendar",
    "ha_remove_todo_item": "calendar",
    "ha_shopping_list": "calendar",
    # helpers
    "ha_list_helpers": "helpers",
    "ha_create_helper": "helpers",
    "ha_update_helper": "helpers",
    "ha_delete_helper": "helpers",
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
    "ha_replace_in_file": "config_files",
    # diagnostics
    "ha_get_logs": "diagnostics",
    "ha_list_problems": "diagnostics",
    "ha_apply_fix": "diagnostics",
    "ha_check_config": "diagnostics",
    "ha_reload": "diagnostics",
    "ha_get_job": "diagnostics",
    "ha_recorder_info": "diagnostics",
    "ha_recorder_purge": "diagnostics",
    "ha_recorder_purge_entities": "diagnostics",
    "ha_recorder_validate": "diagnostics",
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
    # zigbee / matter / thread / bt
    "ha_mesh_network": "zigbee",
    "ha_matter": "zigbee",
    "ha_thread": "zigbee",
    "ha_bluetooth_info": "zigbee",
    # hacs
    "ha_hacs_info": "hacs",
    "ha_hacs_list_repositories": "hacs",
    "ha_hacs_repository_info": "hacs",
    "ha_hacs_install": "hacs",
    "ha_hacs_remove": "hacs",
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


def custom_code_enabled(cfg: dict | None) -> bool:
    """True when Settings → HA tools → custom_code is on (edit custom_components/*.py)."""
    return bool(merged_ha_tools_config(cfg).get("custom_code"))


def filter_tool_names(names: list[str], cfg: dict | None) -> list[str]:
    enabled = enabled_categories(cfg)
    return [n for n in names if tool_category(n) in enabled]


def register_tool_category(name: str, category: str) -> None:
    _TOOL_CATEGORIES[name] = category
