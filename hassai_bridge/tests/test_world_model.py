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
        {"entity_id": "light.releu_living_l1", "state": "off",
         "attributes": {"friendly_name": "Bec balcon"}},
        {"entity_id": "light.releu_living_l3", "state": "off",
         "attributes": {"friendly_name": "Bec living"}},
        {"entity_id": "light.lampa_dormitor_1", "state": "on",
         "attributes": {"friendly_name": "Lampa Dormitor 1"}},
        {"entity_id": "light.lampa_dormitor_2", "state": "on",
         "attributes": {"friendly_name": "Lampa Dormitor 2"}},
        {"entity_id": "light.lamp_pat_a", "state": "on",
         "attributes": {"friendly_name": "Lampă pat"}},
        {"entity_id": "light.lamp_pat_b", "state": "off",
         "attributes": {"friendly_name": "Lampă pat"}},
    ]
    registry = {
        "light.living_main": {"area_id": "living", "name": "Lumina Living"},
        "switch.living_ambient": {"area_id": "living", "name": "Ambient Living"},
        "light.kitchen": {"area_id": "kitchen", "name": "Kitchen Light"},
        "cover.living_blinds": {"area_id": "living", "name": "Jaluzele Living"},
        "light.releu_living_l1": {"area_id": "balcon", "name": "Bec balcon"},
        "light.releu_living_l3": {"area_id": "living", "name": "Bec living"},
        "light.lampa_dormitor_1": {"area_id": "dorm1", "name": "Lampa Dormitor 1"},
        "light.lampa_dormitor_2": {"area_id": "dorm2", "name": "Lampa Dormitor 2"},
        "light.lamp_pat_a": {"area_id": "dorm1", "name": "Lampă pat"},
        "light.lamp_pat_b": {"area_id": "dorm2", "name": "Lampă pat"},
    }
    areas = {
        "living": "Living",
        "kitchen": "Kitchen",
        "balcon": "Balcon",
        "dorm1": "Dormitor 1",
        "dorm2": "Dormitor 2",
    }
    return wm.build_from_rows(states, registry=registry, area_labels=areas)


def test_fold_strips_diacritics():
    assert wm.fold("Lumină") == "lumina"
    assert wm.fold("șțâîă") == "staia"


def test_tokenize_keeps_digits():
    assert "1" in wm.tokenize("dormitor 1")
    assert "2" in wm.tokenize("lampa dormitor 2")
    assert "l1" in wm.tokenize("releu living l1")


def test_build_filters_control_domains():
    nodes = _sample_entities()
    ids = {n.entity_id for n in nodes}
    assert "light.living_main" in ids
    assert "sensor.temp" not in ids


def test_search_living_light():
    nodes = _sample_entities()
    hits = wm.search(nodes, "stinge lumina din living", area="Living", limit=5)
    assert hits
    assert hits[0][0].entity_id in {"light.living_main", "switch.living_ambient", "light.releu_living_l3"}


def test_dormitor_1_beats_dormitor_2():
    nodes = _sample_entities()
    hits = wm.search(nodes, "lampa dormitor 1", limit=5)
    assert hits
    assert hits[0][0].entity_id == "light.lampa_dormitor_1"
    targets, mode = wm.pick_targets(hits)
    assert mode == "unique"
    assert targets == ["light.lampa_dormitor_1"]


def test_dormitor_2_unique():
    nodes = _sample_entities()
    hits = wm.search(nodes, "stinge lampa dormitor 2", limit=5)
    assert hits[0][0].entity_id == "light.lampa_dormitor_2"
    targets, mode = wm.pick_targets(hits)
    assert mode == "unique"
    assert targets == ["light.lampa_dormitor_2"]


def test_friendly_name_beats_entity_id_slug():
    """releu_living_l1 has 'living' in slug but friendly name is Bec balcon."""
    nodes = _sample_entities()
    hits = wm.search(nodes, "bec living", domains=["light"], limit=5)
    assert hits
    assert hits[0][0].entity_id == "light.releu_living_l3"
    targets, mode = wm.pick_targets(hits)
    assert mode == "unique"
    assert targets == ["light.releu_living_l3"]


def test_duplicate_friendly_names_clarify():
    nodes = _sample_entities()
    hits = wm.search(nodes, "lampa pat", limit=5)
    assert len(hits) >= 2
    targets, mode = wm.pick_targets(hits)
    assert mode == "clarify"
    assert set(targets) >= {"light.lamp_pat_a", "light.lamp_pat_b"}


def test_name_tokens_separated_from_slug():
    nodes = _sample_entities()
    balcon = next(n for n in nodes if n.entity_id == "light.releu_living_l1")
    assert "living" in balcon.slug_tokens
    assert "living" not in balcon.name_tokens
    assert "balcon" in balcon.name_tokens


def test_snippet_includes_candidates():
    nodes = _sample_entities()
    text = wm.snippet_for_query(nodes, "kitchen light")
    assert "light.kitchen" in text
    assert "candidates:" in text
