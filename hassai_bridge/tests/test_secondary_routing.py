"""Unit tests for secondary use_for category routing."""

from __future__ import annotations

from services import secondary_routing as sr


def test_defaults_enable_extras_and_disable_ha():
    flags = sr.merged_use_for({})
    assert flags["web_search"] is True
    assert flags["frigate"] is True
    assert flags["entities"] is False
    assert flags["control"] is False


def test_tool_category_mapping():
    assert sr.tool_use_for_category("search_web") == "web_search"
    assert sr.tool_use_for_category("frigate_snapshot") == "frigate"
    assert sr.tool_use_for_category("run_skill") == "skills"
    assert sr.tool_use_for_category("memory_search") == "memory"
    assert sr.tool_use_for_category("hassai_status") == "bridge"
    assert sr.tool_use_for_category("ha_call_service") == "control"
    assert sr.tool_use_for_category("generate_image") is None


def test_secondary_handles_tools_all_or_nothing():
    sec = {"use_for": {"frigate": True, "entities": False}}
    assert sr.secondary_handles_tools(sec, ["frigate_events"]) is True
    assert sr.secondary_handles_tools(sec, ["ha_list_entities"]) is False
    assert sr.secondary_handles_tools(sec, ["frigate_events", "ha_list_entities"]) is False
    assert sr.secondary_handles_tools(None, ["frigate_events"]) is False


def test_normalize_use_for_fills_defaults():
    out = sr.normalize_use_for({"frigate": False, "control": True, "bogus": True})
    assert out["frigate"] is False
    assert out["control"] is True
    assert out["web_search"] is True
    assert "bogus" not in out
