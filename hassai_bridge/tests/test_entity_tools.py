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


def _registry_bundle():
    data = load("registry_sample.json")
    area_labels, area_names = et.index_areas(data["areas"])
    device_labels, _device_names = et.index_devices(data["devices"])
    registry = et.registry_by_entity_id(data["entities"])
    return data, area_labels, area_names, device_labels, registry


def test_merge_entities_and_filter_by_area():
    states = load("states_sample.json")
    data, area_labels, area_names, device_labels, registry = _registry_bundle()
    merged = et.merge_entities(states, registry, area_labels, device_labels)
    rows = et.filter_enriched(merged, {"area_name": "kitchen"})
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "light.kitchen"
    assert rows[0]["area_name"] == "Kitchen"


def test_filter_enriched_excludes_disabled_by_default():
    states = load("states_sample.json")
    data, area_labels, _area_names, device_labels, registry = _registry_bundle()
    merged = et.merge_entities(states, registry, area_labels, device_labels)
    rows = et.filter_enriched(merged, {"domain": "input_boolean"})
    assert rows == []
    rows = et.filter_enriched(merged, {"domain": "input_boolean", "include_disabled": True})
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "input_boolean.test"


def test_format_enriched_list_columns():
    states = load("states_sample.json")
    data, area_labels, _area_names, device_labels, registry = _registry_bundle()
    merged = et.merge_entities(states, registry, area_labels, device_labels)
    filtered = et.filter_enriched(merged, {"domain": "light"})
    page, total = et.paginate_states(filtered, limit=10, offset=0)
    text = et.format_enriched_list(page, total=total, offset=0, limit=10)
    assert "entity_id|name|state|area|device|disabled" in text
    assert "light.living" in text
    assert "Living Room" in text


def test_resolve_area_id_by_name():
    _data, _area_labels, area_names, _device_labels, _registry = _registry_bundle()
    assert et.resolve_area_id(area_names, area_name="Kitchen") == "kitchen"
    assert et.resolve_area_id(area_names, area_id="living_room") == "living_room"


def test_build_entity_update_payload():
    _data, _area_labels, area_names, _device_labels, _registry = _registry_bundle()
    _, label_names = et.index_labels(_data["labels"])
    payload = et.build_entity_update_payload(
        {"name": "New name", "area_name": "Kitchen", "disabled": False, "labels": ["Lights"]},
        area_names,
        label_names,
    )
    assert payload["name"] == "New name"
    assert payload["area_id"] == "kitchen"
    assert payload["disabled_by"] is None
    assert payload["labels"] == ["lights"]


def test_resolve_label_ids_by_name():
    _data, _area_labels, _area_names, _device_labels, _registry = _registry_bundle()
    _, label_names = et.index_labels(_data["labels"])
    assert et.resolve_label_ids(label_names, ["Lights", "climate"]) == ["lights", "climate"]


def test_build_device_update_payload():
    _data, _area_labels, area_names, _device_labels, _registry = _registry_bundle()
    _, label_names = et.index_labels(_data["labels"])
    payload = et.build_device_update_payload(
        {"device_id": "dev-light-living", "area_name": "Kitchen", "labels": ["Lights"]},
        area_names,
        label_names,
    )
    assert payload["device_id"] == "dev-light-living"
    assert payload["area_id"] == "kitchen"
    assert payload["labels"] == ["lights"]


def test_build_area_create_payload():
    _data, _area_labels, _area_names, _device_labels, _registry = _registry_bundle()
    _, label_names = et.index_labels(_data["labels"])
    payload = et.build_area_create_payload({"name": "Office", "labels": ["Climate"]}, label_names)
    assert payload["name"] == "Office"
    assert payload["labels"] == ["climate"]


def test_format_label_list():
    _data, _area_labels, _area_names, _device_labels, _registry = _registry_bundle()
    text = et.format_label_list(_data["labels"])
    assert "label_id|name|color|icon" in text
    assert "lights|Lights" in text


def test_can_set_state_helpers_only():
    assert et.can_set_state("input_boolean.test") is True
    assert et.can_set_state("light.kitchen") is False


def test_filter_registry_entries():
    data, area_labels, _area_names, _device_labels, _registry = _registry_bundle()
    rows = et.filter_registry_entries(data["entities"], {"search": "kitchen"})
    text = et.format_registry_list(rows, area_labels)
    assert "light.kitchen" in text
    assert "Kitchen" in text
