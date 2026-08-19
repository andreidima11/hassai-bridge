import json
from pathlib import Path

from services import entity_tools as et

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_filter_states_search_and_domain():
    states = load("states_sample.json")
    rows = et.filter_states(states, {"domain": "light"})
    assert len(rows) == 2
    rows = et.filter_states(states, {"search": "kitchen"})
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "light.kitchen"


def test_filter_states_includes_update_domain_by_default():
    states = load("states_sample.json")
    rows = et.filter_states(states, {"search": "bridge"})
    assert any(r["entity_id"] == "update.bridge" for r in rows)


def test_filter_states_state_filter():
    states = load("states_sample.json")
    rows = et.filter_states(states, {"state_filter": "on"})
    assert all(r["state"] == "on" for r in rows)


def test_paginate_and_format_list():
    states = load("states_sample.json")
    filtered = et.filter_states(states, {})
    sorted_rows = et.sort_states(filtered, "entity_id")
    page, total = et.paginate_states(sorted_rows, limit=2, offset=0)
    text = et.format_entity_list(page, total=total, offset=0, limit=2)
    assert "showing 1-2 of 5" in text
    assert "offset=2" in text
    assert "light.kitchen" in text


def test_format_state_detail_full_and_capabilities():
    state = load("states_sample.json")[4]
    text = et.format_state_detail(
        state,
        {"include_timestamps": True, "include_capabilities": True, "full_attributes": True},
    )
    assert "climate.living" in text
    assert "hvac_modes" in text
    assert "capabilities:" in text
    assert "temp_range=16-28" in text


def test_format_services_index():
    services = {
        "light": {
            "turn_on": {"brightness": {}, "rgb_color": {}},
            "turn_off": {},
        },
        "homeassistant": {"reload": {}},
    }
    text = et.format_services_index(services, "light")
    assert "light.turn_on" in text
    assert "brightness" in text
    assert "homeassistant.reload" not in text


def test_render_ha_agent_prompt_tools_placeholder():
    out = et.render_ha_agent_prompt("Tools: {tools}.", ["ha_get_state", "ha_list_entities"])
    assert "ha_get_state" in out
    assert "ha_list_entities" in out
    assert "{tools}" not in out


def test_render_ha_agent_prompt_default():
    out = et.render_ha_agent_prompt("", ["ha_call_service"])
    assert "ha_call_service" in out
    assert "Entities" in out
