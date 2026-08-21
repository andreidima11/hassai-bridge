"""Tests for chat greeting atmosphere helpers."""

from __future__ import annotations

from services.atmosphere import _map_weather, _pick_weather


def test_map_weather_known_states():
    assert _map_weather("rainy") == "rainy"
    assert _map_weather("pouring") == "rainy"
    assert _map_weather("sunny") == "sunny"
    assert _map_weather("clear-night") == "clear_night"
    assert _map_weather("unknown") is None


def test_pick_weather_prefers_home_entity():
    states = [
        {"entity_id": "weather.forecast_home", "state": "cloudy", "attributes": {"temperature": 11}},
        {"entity_id": "weather.home", "state": "rainy", "attributes": {"temperature": 9, "temperature_unit": "°C"}},
        {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
    ]
    out = _pick_weather(states)
    assert out["weather"] == "rainy"
    assert out["temp"] == 9.0
    assert "°C" in out["temp_unit"]


def test_pick_weather_empty():
    assert _pick_weather([]) == {}
    assert _pick_weather([{"entity_id": "weather.x", "state": "unavailable", "attributes": {}}]) == {}
