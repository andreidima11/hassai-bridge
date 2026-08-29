"""Unit tests for seasonal greeting pool helpers (no LLM)."""

from services.greeting_pool import (
    _clean_item,
    _parse_llm_items,
    normalize_greetings_cfg,
    season_key,
    upcoming_holidays,
)


def test_normalize_defaults_and_bounds():
    n = normalize_greetings_cfg({})
    assert n["refresh_days"] == 7
    assert n["pool_size"] == 40
    assert n["provider_id"] == ""
    assert n["model"] == ""
    assert normalize_greetings_cfg({"refresh_days": 0})["refresh_days"] == 1
    assert normalize_greetings_cfg({"pool_size": 999})["pool_size"] == 80
    assert normalize_greetings_cfg({"provider_id": " openai_1 ", "model": " gpt "})["provider_id"] == "openai_1"
    assert normalize_greetings_cfg({"provider_id": " openai_1 ", "model": " gpt "})["model"] == "gpt"


def test_season_key_december_christmas():
    from datetime import date
    sk = season_key("en", date(2026, 12, 20))
    assert sk.startswith("2026-12")
    assert "christmas" in sk


def test_upcoming_holidays_ro_includes_national_day():
    from datetime import date
    hols = upcoming_holidays("ro", date(2026, 11, 25), horizon_days=20)
    ids = {h["id"] for h in hols}
    assert "national_day" in ids or "st_andrew" in ids


def test_parse_llm_json_array():
    raw = '''```json
[
  {"tags":["morning","general"],"title":{"en":"Good morning","ro":"Bună dimineața"},"hint":{"en":"How can I help?","ro":"Cu ce te ajut?"}},
  {"tags":["christmas"],"title":{"en":"Merry Christmas","ro":"Crăciun fericit"},"hint":{"en":"Ask me anything.","ro":"Întreabă-mă orice."}}
]
```'''
    items = _parse_llm_items(raw)
    assert len(items) == 2
    assert "christmas" in items[1]["tags"]
    assert items[0]["title"]["ro"]


def test_clean_item_rejects_empty():
    assert _clean_item({}) is None
    assert _clean_item({"tags": ["general"], "title": {"en": "Hi"}, "hint": {"en": "There"}})["tags"] == ["general"]
