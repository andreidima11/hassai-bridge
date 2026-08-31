"""Tests for HA tool category gating."""

from services.ha_tool_access import (
    CATEGORY_KEYS,
    custom_code_enabled,
    enabled_categories,
    filter_tool_names,
    merged_ha_tools_config,
    tool_category,
    tool_enabled,
)


def test_default_categories_custom_code_off():
    cfg = {}
    enabled = enabled_categories(cfg)
    assert "custom_code" in CATEGORY_KEYS
    assert "custom_code" not in enabled
    assert enabled == set(CATEGORY_KEYS.keys()) - {"custom_code"}


def test_custom_code_opt_in():
    assert custom_code_enabled({}) is False
    assert custom_code_enabled({"ha_tools": {"custom_code": True}}) is True
    assert custom_code_enabled({"ha_tools": {"custom_code": False}}) is False


def test_disabled_category_filters_tools():
    cfg = {"ha_tools": {"backups": False, "restart": False}}
    assert "backups" not in enabled_categories(cfg)
    assert tool_enabled("ha_list_backups", cfg) is False
    assert tool_enabled("ha_list_entities", cfg) is True
    assert tool_enabled("ha_reboot_host", cfg) is False


def test_filter_tool_names():
    cfg = {"ha_tools": {"network": False}}
    names = filter_tool_names(
        ["ha_ping_host", "ha_get_state", "ha_check_port"],
        cfg,
    )
    assert names == ["ha_get_state"]


def test_new_supervisor_tools_have_categories():
    assert tool_category("ha_create_backup") == "backups"
    assert tool_category("ha_restart_addon") == "addons"
    assert tool_category("ha_mesh_network") == "zigbee"


def test_merged_config_defaults_true():
    merged = merged_ha_tools_config({"ha_tools": {"upload": False}})
    assert merged["upload"] is False
    assert merged["entities"] is True
    assert merged["custom_code"] is False
