"""Tests for Settings-disabled tool group enable flow."""

from services import tool_enable as te


def test_resolve_group_aliases():
    assert te.resolve_group("browser") == "bridge:browser"
    assert te.resolve_group("backups") == "ha:backups"
    assert te.resolve_group("searxng") == "feature:searxng"
    assert te.resolve_group("ha_dashboards") == "ha:dashboards"
    assert te.resolve_group("nope") is None


def test_session_grant_overrides_settings():
    te.clear_session("s1")
    cfg = {"bridge_tools": {"browser": False}, "browser": {"enabled": False}}
    assert not te.effectively_enabled("bridge:browser", cfg, "s1")
    te.grant_session("s1", "bridge:browser")
    assert te.effectively_enabled("bridge:browser", cfg, "s1")
    cfg2 = te.apply_session_overrides(cfg, "s1")
    assert cfg2["bridge_tools"]["browser"] is True
    te.clear_session("s1")


def test_disabled_groups_lists_browser_when_off():
    cfg = {
        "bridge_tools": {"browser": False, "memory": True, "status": True, "control": True, "media": True},
        "ha_tools": {k: True for k in __import__("services.ha_tool_access", fromlist=["CATEGORY_KEYS"]).CATEGORY_KEYS},
        "searxng": {"enabled": True},
        "frigate": {"enabled": True},
    }
    keys = {k for k, _ in te.disabled_groups(cfg)}
    assert "bridge:browser" in keys
    hint = te.system_hint(cfg, None)
    assert "request_enable_tools" in hint
    assert "browser" in hint
    assert "Never say you cannot find them" in hint


def test_canonical_for_tool():
    assert te.canonical_for_tool("browser_interact") == "bridge:browser"
    assert te.canonical_for_tool("ha_create_backup") == "ha:backups"
    assert te.canonical_for_tool("search_web") == "feature:searxng"


def test_is_ha_tool_ignores_settings_toggle():
    from services import homeassistant as ha

    assert ha.is_ha_tool("ha_update_entity") is True
    assert ha.is_ha_tool("ha_update_entity", {"ha_tools": {"registry": False}}) is True
    assert ha.is_ha_tool("not_a_tool") is False
