"""World model / house index unit tests."""

from services import world_model as wm


def _sample_entities():
    states = [
        {"entity_id": "light.living_main", "state": "on",
         "attributes": {"friendly_name": "Lumina Living"}},
        {"entity_id": "switch.living_ambient", "state": "off",
         "attributes": {"friendly_name": "Ambient Living"}},
        {"entity_id": "light.kitchen", "state": "off",
         "attributes": {"friendly_name": "Kitchen Light"}},
        {"entity_id": "cover.living_blinds", "state": "open",
         "attributes": {"friendly_name": "Jaluzele Living"}},
        {"entity_id": "sensor.temp", "state": "22",
         "attributes": {"friendly_name": "Temp"}},
    ]
    registry = {
        "light.living_main": {"area_id": "living", "name": "Lumina Living"},
        "switch.living_ambient": {"area_id": "living", "name": "Ambient Living"},
        "light.kitchen": {"area_id": "kitchen", "name": "Kitchen Light"},
        "cover.living_blinds": {"area_id": "living", "name": "Jaluzele Living"},
    }
    areas = {"living": "Living", "kitchen": "Kitchen"}
    return wm.build_from_rows(states, registry=registry, area_labels=areas)


def test_fold_strips_diacritics():
    assert wm.fold("Lumină") == "lumina"
    assert wm.fold("șțâîă") == "staia"


def test_build_filters_control_domains():
    nodes = _sample_entities()
    ids = {n.entity_id for n in nodes}
    assert "light.living_main" in ids
    assert "sensor.temp" not in ids


def test_search_living_light():
    nodes = _sample_entities()
    hits = wm.search(nodes, "stinge lumina din living", area="Living", limit=5)
    assert hits
    assert hits[0][0].entity_id in {"light.living_main", "switch.living_ambient"}


def test_snippet_includes_candidates():
    nodes = _sample_entities()
    text = wm.snippet_for_query(nodes, "kitchen light")
    assert "light.kitchen" in text
    assert "candidates:" in text
