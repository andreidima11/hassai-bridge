"""Tests for Thinking timeline activity labels."""

from __future__ import annotations

import json

from services import activity_labels as al
from services import tool_awareness as taw
from services import toolkits as tk


def test_tool_detail_list_entities():
    assert "dormitor" in al.tool_detail(
        "ha_list_entities",
        {"search": "dormitor", "domain": "light,switch"},
    )


def test_tool_detail_explain_and_logs():
    assert "light.banda" in al.tool_detail(
        "ha_explain_event",
        {"entity_id": "light.banda", "event": "turned_on"},
    )
    assert "turned_on" in al.tool_detail(
        "ha_explain_event",
        {"entity_id": "light.banda", "event": "turned_on"},
    )
    assert "addon" in al.tool_detail(
        "ha_get_logs",
        {"source": "addon", "slug": "z2m"},
    )
    assert "z2m" in al.tool_detail("ha_get_logs", {"source": "addon", "slug": "z2m"})


def test_tool_detail_background_tasks():
    out = al.tool_detail(
        "background_tasks",
        {"action": "wait_for_state", "title": "Wait door", "entity_id": "binary_sensor.door"},
    )
    assert "wait_for_state" in out
    assert "door" in out


def test_result_preview_explain_json():
    payload = json.dumps({
        "change": "off → on",
        "cause_type": "automation",
        "confidence": "confirmed",
        "summary": "long text ignored when structured fields exist",
    })
    preview = al.tool_result_preview("ha_explain_event", payload)
    assert "off → on" in preview
    assert "confirmed" in preview


def test_result_preview_list_showing_ro():
    text = "showing 1-2 of 88\nlight.a\ton\nlight.b\toff"
    assert al.tool_result_preview("ha_list_entities", text, lang="ro") == "88 găsite"
    assert al.tool_result_preview("ha_list_entities", text, lang="en") == "88 found"


def test_result_preview_activate_toolkits_no_json():
    payload = json.dumps({
        "activated": ["control", "entities"],
        "denied": [],
        "active_packs": ["control", "entities"],
        "tool_count": 40,
        "hint": "Domain tools for the activated packs are now available.",
    })
    out = al.tool_result_preview("activate_toolkits", payload, lang="ro")
    assert "{" not in out
    assert "control" in out and "entities" in out
    assert "Încărcat" in out


def test_result_preview_ha_call_service_strips_header():
    text = (
        "[Home Assistant — ha_call_service]\n"
        "OK: called switch.turn_off on switch.lampa_flori_etaj"
    )
    out = al.tool_result_preview("ha_call_service", text, lang="ro")
    assert "Home Assistant" not in out
    assert "switch.turn_off" in out
    assert "Apelat" in out


def test_result_preview_error():
    assert al.tool_result_preview("ha_get_state", "Error: not found").startswith("Error")


def test_awareness_still_wired():
    assert taw.looks_like_explain_event("De ce s-a aprins lumina?")
    assert tk.is_core_tool("ha_explain_event")
    playbook = taw.build_tool_playbook(["ha_explain_event"])
    assert "ha_explain_event" in playbook
