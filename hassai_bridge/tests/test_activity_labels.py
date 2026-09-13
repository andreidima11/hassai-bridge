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


def test_result_preview_list_showing():
    text = "showing 1-2 of 12\nlight.a\ton\nlight.b\toff"
    assert "12 found" in al.tool_result_preview("ha_list_entities", text)


def test_result_preview_error():
    assert al.tool_result_preview("ha_get_state", "Error: not found").startswith("Error")


def test_awareness_still_wired():
    assert taw.looks_like_explain_event("De ce s-a aprins lumina?")
    assert tk.is_core_tool("ha_explain_event")
    playbook = taw.build_tool_playbook(["ha_explain_event"])
    assert "ha_explain_event" in playbook
