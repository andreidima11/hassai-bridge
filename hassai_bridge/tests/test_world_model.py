"""World model: index building, exact matching, agent index block."""

from __future__ import annotations

from services import world_model as wm


def _home():
    states = [
        {"entity_id": "light.lampa_dormitor_1", "state": "off",
         "attributes": {"friendly_name": "Lampa Dormitor 1"}},
        {"entity_id": "light.lampa_dormitor_2", "state": "on",
         "attributes": {"friendly_name": "Lampa Dormitor 2"}},
        {"entity_id": "light.living_main", "state": "on",
         "attributes": {"friendly_name": "Lumină Living"}},
        {"entity_id": "switch.releu_1", "state": "off",
         "attributes": {"friendly_name": "Bec Balcon"}},
        {"entity_id": "cover.living_blind", "state": "closed",
         "attributes": {"friendly_name": "Jaluzea"}},
        {"entity_id": "cover.bedroom_blind", "state": "open",
         "attributes": {"friendly_name": "Jaluzea"}},
        {"entity_id": "sensor.temp", "state": "21",
         "attributes": {"friendly_name": "Temperatura"}},
        {"entity_id": "light.hidden", "state": "on",
         "attributes": {"friendly_name": "Hidden"}},
    ]
    registry = {
        "light.lampa_dormitor_1": {"area_id": "bedroom"},
        "light.lampa_dormitor_2": {"area_id": "bedroom"},
        "light.living_main": {"area_id": "living"},
        "switch.releu_1": {"area_id": "balcony", "device_id": "dev1"},
        "cover.living_blind": {"area_id": "living"},
        "cover.bedroom_blind": {"area_id": "bedroom"},
        "light.hidden": {"hidden_by": "user"},
    }
    areas = {"bedroom": "Dormitor", "living": "Living", "balcony": "Balcon"}
    devices = {"dev1": "Sonoff Relay"}
    return wm.build_from_rows(
        states, registry=registry, area_labels=areas, device_labels=devices,
    )


def test_fold_strips_diacritics_and_punctuation():
    assert wm.fold("Lumină  Living!") == "lumina living"
    assert wm.tokenize("Lampa Dormitor 1") == ["lampa", "dormitor", "1"]


def test_build_filters_domains_and_hidden():
    ents = _home()
    ids = {e.entity_id for e in ents}
    assert "sensor.temp" not in ids
    assert "light.hidden" not in ids
    relay = wm.by_id(ents, "switch.releu_1")
    assert relay.name == "Bec Balcon"
    assert relay.area == "Balcon"
    assert relay.device_name == "Sonoff Relay"


def test_find_exact_distinguishes_numbered_lamps():
    ents = _home()
    hits = wm.find_exact(ents, "lampa dormitor 1")
    assert [h.entity_id for h in hits] == ["light.lampa_dormitor_1"]
    hits = wm.find_exact(ents, "Lampa Dormitor 2")
    assert [h.entity_id for h in hits] == ["light.lampa_dormitor_2"]


def test_find_exact_partial_name_is_not_a_match():
    ents = _home()
    assert wm.find_exact(ents, "lampa dormitor") == []
    assert wm.find_exact(ents, "lampa") == []
    assert wm.find_exact(ents, "dormitor") == []


def test_find_exact_accepts_name_plus_area():
    ents = _home()
    hits = wm.find_exact(ents, "jaluzea din living")
    assert [h.entity_id for h in hits] == ["cover.living_blind"]
    hits = wm.find_exact(ents, "jaluzea dormitor")
    assert [h.entity_id for h in hits] == ["cover.bedroom_blind"]


def test_find_exact_returns_all_duplicates():
    ents = _home()
    hits = wm.find_exact(ents, "jaluzea")
    assert {h.entity_id for h in hits} == {"cover.living_blind", "cover.bedroom_blind"}


def test_find_exact_by_friendly_name_of_relay():
    ents = _home()
    hits = wm.find_exact(ents, "bec balcon")
    assert [h.entity_id for h in hits] == ["switch.releu_1"]


def test_index_block_lists_every_controllable_entity():
    ents = _home()
    block = wm.index_block(ents)
    assert block.startswith("entities (entity_id | name | area | state):")
    for e in ents:
        assert f"- {e.entity_id} | {e.name} | {e.area or '-'} | {e.state}" in block
    assert "sensor.temp" not in block


def test_index_block_trims_with_hint():
    ents = _home()
    block = wm.index_block(ents, limit=3)
    assert block.count("\n- ") == 3
    assert "more" in block and "ha_list_entities" in block


def test_areas_summary():
    summary = wm.areas_summary(_home())
    assert summary[0].startswith("Dormitor (3)")
