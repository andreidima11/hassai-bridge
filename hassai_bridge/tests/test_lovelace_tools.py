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
