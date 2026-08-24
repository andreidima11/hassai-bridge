import json
from pathlib import Path

from services import entity_tools as et

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_filter_states_search_and_domain():
    states = load("states_sample.json")
    rows = et.filter_states(states, {"domain": "light"})
    # domain=light expands to light+switch (relay bulbs)
    assert {r["entity_id"] for r in rows} == {
        "light.living", "light.kitchen", "switch.dormitor_bec",
    }
    rows = et.filter_states(states, {"search": "kitchen"})
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "light.kitchen"


def test_filter_states_light_domain_finds_relay_switch_by_search():
    states = load("states_sample.json")
    rows = et.filter_states(states, {"domain": "light", "search": "dormitor"})
    assert [r["entity_id"] for r in rows] == ["switch.dormitor_bec"]


def test_filter_states_comma_domains():
    states = load("states_sample.json")
    rows = et.filter_states(states, {"domain": "climate,sensor"})
    assert {r["entity_id"] for r in rows} == {"climate.living", "sensor.temp"}


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
    assert "showing 1-2 of 6" in text
    assert "offset=2" in text
    assert "climate.living" in text or "light.kitchen" in text or "light.living" in text


def test_default_prompt_mentions_relay_switches():
    out = et.render_ha_agent_prompt("", ["ha_list_entities", "ha_call_service"])
    assert "switch.*" in out
    assert "light,switch" in out or "domain=light,switch" in out


def test_default_prompt_device_status_not_automation():
    out = et.render_ha_agent_prompt("", ["ha_list_entities", "ha_get_state", "ha_get_automation"])
    assert "ha_get_state" in out
    assert "Do NOT use ha_list_automations" in out or "not the device itself" in out
    assert "merge irigatorul" in out or "is it on/running" in out


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


def test_parse_entity_id_args_dedupes():
    ids = et.parse_entity_id_args({"entity_id": "light.a", "entity_ids": ["light.a", "light.b"]})
    assert ids == ["light.a", "light.b"]


def test_format_history_response():
    payload = load("history_sample.json")
    text = et.format_history_response(payload, ["light.kitchen"], max_rows=10)
    assert "light.kitchen" in text
    assert "on" in text
    assert "off" in text


def test_format_logbook_entries():
    entries = load("logbook_sample.json")
    text = et.format_logbook_entries(entries, max_rows=10)
    assert "light.kitchen" in text
    assert "turned on" in text


def test_filter_entity_sources():
    sources = load("entity_source_sample.json")
    rows = et.filter_entity_sources(sources, {"entity_id": "light.kitchen"})
    text = et.format_entity_source_list(rows)
    assert "light.kitchen|shelly" in text


def test_filter_exposed_entities():
    exposed = load("exposed_sample.json")
    rows = et.filter_exposed_entities(exposed, {"assistant": "conversation"})
    text = et.format_exposed_entity_list(rows)
    assert "light.kitchen|conversation" in text
    assert "climate.living" in text
    assert "sensor.temp" not in text
    assert len(rows) == 2


def test_build_expose_entity_payload():
    payload = et.build_expose_entity_payload(
        {"entity_ids": ["light.a", "Lights"], "should_expose": True, "assistants": ["conversation"]}
    )
    assert payload["entity_ids"] == ["light.a", "Lights"]
    assert payload["should_expose"] is True
    assert payload["assistants"] == ["conversation"]


def test_index_floors_and_area_floor_name():
    floors = load("floors_sample.json")
    _floor_labels, floor_names = et.index_floors(floors)
    assert et.resolve_floor_id(floor_names, floor_name="First Floor") == "first"
    payload = et.build_area_create_payload({"name": "Office", "floor_name": "Ground Floor"}, {}, floor_names)
    assert payload["floor_id"] == "ground"


def test_format_floor_list():
    text = et.format_floor_list(load("floors_sample.json"))
    assert "floor_id|name|level|icon" in text
    assert "ground|Ground Floor" in text


def test_format_automation_and_script_lists():
    states = load("domain_states_sample.json")
    automations = et.filter_states(states, {"domain": "automation"})
    scripts = et.filter_states(states, {"domain": "script"})
    scenes = et.filter_states(states, {"domain": "scene"})
    auto_text = et.format_automation_list(automations, total=len(automations), offset=0, limit=10)
    script_text = et.format_script_list(scripts, total=len(scripts), offset=0, limit=10)
    scene_text = et.format_scene_list(scenes, total=len(scenes), offset=0, limit=10)
    assert "automation.morning" in auto_text
    assert "script.goodnight" in script_text
    assert "scene.movie" in scene_text
    assert "2 entities" in scene_text


def test_format_automation_detail():
    states = load("domain_states_sample.json")
    text = et.format_automation_detail(states[0])
    assert "automation.morning" in text
    assert "id: morning" in text
    assert "automation:" in text


def test_format_automation_config_summary():
    config = {
        "alias": "Pulpa",
        "description": "Test automation",
        "mode": "single",
        "triggers": [{"platform": "state", "entity_id": "binary_sensor.door"}],
        "conditions": [],
        "actions": [{"service": "light.turn_off", "target": {"entity_id": "light.kitchen"}}],
    }
    text = et.format_automation_config(config)
    assert "alias: Pulpa" in text
    assert "triggers (1):" in text
    assert "platform=state" in text
    assert "actions (1):" in text
    assert "light.turn_off" in text


def test_resolve_config_entity_by_search_and_entity_id():
    states = load("domain_states_sample.json")
    resolved = et.resolve_config_entity(states, "automation", search="pulpa")
    assert isinstance(resolved, str)
    assert "no automation" in resolved

    resolved = et.resolve_config_entity(states, "automation", search="morning")
    assert resolved == ("automation.morning", "morning", states[0])

    resolved = et.resolve_config_entity(states, "automation", entity_id="automation.morning")
    assert resolved[0] == "automation.morning"
    assert resolved[1] == "morning"

    resolved = et.resolve_config_entity(states, "script", search="goodnight")
    assert resolved == ("script.goodnight", "goodnight", states[1])


def test_filter_config_entries():
    entries = et.filter_config_entries(load("config_entries_sample.json"), {"domain": "mqtt"})
    text = et.format_config_entry_list(entries)
    assert "abc123|mqtt|MQTT Broker" in text
    assert "shelly" not in text


def test_format_config_entry_detail():
    entry = load("config_entries_sample.json")[1]
    text = et.format_config_entry_detail(entry)
    assert "setup_error" in text
    assert "cannot_connect" in text


def test_filter_statistic_ids_and_format_statistics():
    ids = et.filter_statistic_ids(
        [{"statistic_id": "sensor.temperature"}, {"statistic_id": "sensor.humidity"}],
        {"search": "temp"},
    )
    text = et.format_statistic_id_list(ids)
    assert "sensor.temperature" in text
    assert "sensor.humidity" not in text
    stats_text = et.format_statistics_response(
        load("statistics_sample.json"),
        ["sensor.temperature"],
        max_rows=10,
    )
    assert "mean=21.5" in stats_text


def test_format_group_zone_person_lists():
    states = load("domain_states_sample.json")
    group_states = [
        {
            "entity_id": "group.lights",
            "state": "on",
            "attributes": {"friendly_name": "All lights", "entity_id": ["light.a", "light.b"]},
        }
    ]
    zone_states = [
        {
            "entity_id": "zone.home",
            "state": "0",
            "attributes": {"friendly_name": "Home", "radius": 100, "passive": False},
        }
    ]
    person_states = [
        {
            "entity_id": "person.john",
            "state": "home",
            "attributes": {"friendly_name": "John", "user_id": "uid1", "device_trackers": ["device_tracker.phone"]},
        }
    ]
    assert "2 members" in et.format_group_list(group_states, total=1, offset=0, limit=10)
    assert "zone.home" in et.format_zone_list(zone_states, total=1, offset=0, limit=10)
    assert "person.john" in et.format_person_list(person_states, total=1, offset=0, limit=10)
