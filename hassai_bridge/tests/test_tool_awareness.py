"""Tests for live tool playbook / explain-event intent."""

from __future__ import annotations

from services import tool_awareness as taw
from services import toolkits as tk


def test_looks_like_explain_event_ro_en():
    assert taw.looks_like_explain_event("De ce s-a aprins banda din dormitor?")
    assert taw.looks_like_explain_event("Why did the kitchen light turn on?")
    assert taw.looks_like_explain_event("Cine a stins lumina?")
    assert taw.looks_like_explain_event("Who turned off the porch light?")
    assert not taw.looks_like_explain_event("Aprinde lumina din dormitor")
    assert not taw.looks_like_explain_event("Ce temperatură e afară?")


def test_playbook_only_lists_present_tools():
    text = taw.build_tool_playbook(["ha_explain_event", "search_web", "ha_list_entities"])
    assert "ha_explain_event" in text
    assert "search_web" in text
    assert "Zigbee2MQTT" not in text  # ha_get_logs not present
    assert "THIS turn" in text


def test_playbook_empty_without_matching_tools():
    assert taw.build_tool_playbook(["ha_list_areas"]) == ""
    assert taw.build_tool_playbook([]) == ""


def test_explain_event_is_dynamic_core():
    assert tk.is_core_tool("ha_explain_event")
