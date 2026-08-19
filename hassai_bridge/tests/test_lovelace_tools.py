import json
from pathlib import Path

import pytest

from services import lovelace_tools as lt

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_pick_view_by_path():
    cfg = load("lovelace_sections.json")
    idx, view = lt.pick_view(cfg, {"view_path": "home"})
    assert idx == 0
    assert view["title"] == "Home"


def test_pick_view_missing_raises():
    cfg = load("lovelace_sections.json")
    with pytest.raises(RuntimeError, match="no view with path"):
        lt.pick_view(cfg, {"view_path": "kitchen"})


def test_pick_view_default_is_first():
    cfg = load("lovelace_sections.json")
    idx, view = lt.pick_view(cfg, {})
    assert idx == 0


def test_upsert_card_sections_appends_to_section():
    cfg = load("lovelace_sections.json")
    idx, view = lt.pick_view(cfg, {"view_path": "home"})
    container = lt.card_container(view, {"section_index": 1})
    cards = list(container.cards)
    cards.append({"type": "tile", "entity": "sensor.temp"})
    container.write_back(cards)
    cfg["views"][idx] = view

    section_cards = cfg["views"][0]["sections"][1]["cards"]
    assert section_cards[-1]["entity"] == "sensor.temp"
    assert len(section_cards) == 2


def test_upsert_card_masonry_uses_view_cards():
    cfg = load("lovelace_masonry.json")
    idx, view = lt.pick_view(cfg, {"view_path": "legacy"})
    container = lt.card_container(view, {})
    cards = list(container.cards)
    cards.append({"type": "markdown", "content": "hi"})
    container.write_back(cards)
    cfg["views"][idx] = view

    assert cfg["views"][0]["cards"][-1]["type"] == "markdown"


def test_summarize_dashboard_lists_sections():
    cfg = load("lovelace_sections.json")
    text = lt.summarize_dashboard(None, cfg, mode="storage", include_cards=True)
    assert "type=sections" in text
    assert "light.living" in text
    assert "light.kitchen" in text


def test_parse_lovelace_url():
    assert lt.parse_lovelace_url("/lovelace/kitchen") == {"url_path": None, "view_path": "kitchen"}
    assert lt.parse_lovelace_url("/dashboard-energy/home") == {
        "url_path": "energy",
        "view_path": "home",
    }


def test_upsert_view_appends_sections_view():
    cfg = load("lovelace_sections.json")
    idx, view, action = lt.upsert_view_in_config(
        cfg,
        {"title": "Kitchen", "path": "kitchen", "view_type": "sections"},
    )
    assert action.startswith("created view")
    assert cfg["views"][idx]["path"] == "kitchen"
    assert cfg["views"][idx]["type"] == "sections"
    assert cfg["views"][idx]["sections"]


def test_nested_card_path_replace():
    view = {
        "title": "Home",
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {"type": "tile", "entity": "light.a"},
                            {"type": "tile", "entity": "light.b"},
                        ],
                    }
                ],
            }
        ],
    }
    action, _ = lt.mutate_card_in_view(
        view,
        {"section_index": 0, "card_path": "0.1"},
        card={"type": "tile", "entity": "light.c"},
    )
    assert "replaced nested" in action
    nested = view["sections"][0]["cards"][0]["cards"]
    assert nested[1]["entity"] == "light.c"


def test_yaml_dashboard_file():
    assert lt.yaml_dashboard_file(None) == "ui-lovelace.yaml"
    assert lt.yaml_dashboard_file("energy-home") == "dashboards/energy-home.yaml"


def test_resolve_dashboard_args():
    merged = lt.resolve_dashboard_args({
        "dashboard_url": "/dashboard-energy/home",
        "card": {"type": "tile"},
    })
    assert merged["url_path"] == "energy"
    assert merged["view_path"] == "home"
    assert merged["card"]["type"] == "tile"


def test_delete_view_in_config():
    cfg = load("lovelace_sections.json")
    cfg["views"].append({
        "title": "Lights",
        "path": "lights",
        "type": "sections",
        "sections": [{"type": "grid", "cards": []}],
    })
    assert len(cfg["views"]) == 2
    idx, view, action = lt.delete_view_in_config(cfg, {"view_path": "lights"})
    assert "deleted view" in action
    assert len(cfg["views"]) == 1
    assert view["path"] == "lights"


def test_delete_last_view_raises():
    cfg = {"views": [{"title": "Only", "path": "only", "type": "sections", "sections": []}]}
    with pytest.raises(RuntimeError, match="last remaining view"):
        lt.delete_view_in_config(cfg, {"view_path": "only"})


def test_append_card_to_yaml_sections():
    cfg = load("lovelace_sections.json")
    card = {"type": "tile", "entity": "sensor.new"}
    updated, action = lt.append_card_to_yaml(cfg, {"view_path": "home", "section_index": 0}, card)
    assert "appended card" in action
    cards = updated["views"][0]["sections"][0]["cards"]
    assert cards[-1]["entity"] == "sensor.new"


def test_match_dashboard_by_id_and_url_path():
    rows = [
        {"id": "abc123", "url_path": "test-dashboard", "title": "Test", "mode": "storage"},
        {"id": "def456", "url_path": "energy-home", "title": "Energy", "mode": "storage"},
    ]
    by_id = lt.match_dashboard(rows, {"dashboard_id": "abc123"})
    assert by_id["url_path"] == "test-dashboard"
    by_path = lt.match_dashboard(rows, {"url_path": "test_dashboard"})
    assert by_path["id"] == "abc123"
    by_title = lt.match_dashboard(rows, {"title": "Energy"})
    assert by_title["url_path"] == "energy-home"
