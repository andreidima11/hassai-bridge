"""Tests for new HA lifecycle tool categories and helpers."""

from services import ha_lifecycle_tools as hlt
from services.ha_tool_access import (
    CATEGORY_KEYS,
    enabled_categories,
    tool_category,
    tool_enabled,
)


def test_new_categories_exist():
    for key in ("calendar", "helpers", "hacs"):
        assert key in CATEGORY_KEYS
    assert "calendar" in enabled_categories({})


def test_lifecycle_tools_categorized():
    assert tool_category("ha_list_calendars") == "calendar"
    assert tool_category("ha_add_todo_item") == "calendar"
    assert tool_category("ha_create_helper") == "helpers"
    assert tool_category("ha_list_traces") == "automations"
    assert tool_category("ha_get_trace") == "automations"
    assert tool_category("ha_notify") == "control"
    assert tool_category("ha_media_play") == "control"
    assert tool_category("ha_delete_config_entry") == "integrations"
    assert tool_category("ha_create_scene") == "automations"
    assert tool_category("ha_recorder_purge") == "diagnostics"
    assert tool_category("ha_matter") == "zigbee"
    assert tool_category("ha_hacs_install") == "hacs"


def test_disable_calendar_category():
    cfg = {"ha_tools": {"calendar": False}}
    assert tool_enabled("ha_list_calendars", cfg) is False
    assert tool_enabled("ha_list_entities", cfg) is True


def test_all_lifecycle_specs_have_handlers():
    missing = set(hlt.TOOL_SPECS) - set(hlt.HANDLERS)
    assert not missing, f"Missing handlers: {sorted(missing)}"


def test_helper_domains():
    assert "input_boolean" in hlt.HELPER_DOMAINS
    assert "schedule" in hlt.HELPER_DOMAINS
    assert hlt._helper_domain("timer") == "timer"
    assert hlt._helper_domain("light") is None


def test_config_id_slug():
    assert hlt._config_id({}, {"name": "Evening Lights!"}) == "evening_lights"


def test_todo_list_crud_categorized():
    assert tool_category("ha_create_todo_list") == "calendar"
    assert tool_category("ha_delete_todo_list") == "calendar"
    assert tool_category("ha_clear_todo_list") == "calendar"
    assert "ha_create_todo_list" in hlt.TOOL_SPECS
    assert "ha_delete_todo_list" in hlt.HANDLERS
