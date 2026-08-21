"""Lightweight chat greeting context (weather) from Home Assistant."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("hassai.atmosphere")

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_CACHE_TTL = 900.0  # 15 minutes — greeting context, not realtime dashboard

_WEATHER_MAP = {
    "clear-night": "clear_night",
    "cloudy": "cloudy",
    "fog": "foggy",
    "hail": "stormy",
    "lightning": "stormy",
    "lightning-rainy": "stormy",
    "partlycloudy": "cloudy",
    "pouring": "rainy",
    "rainy": "rainy",
    "snowy": "snowy",
    "snowy-rainy": "snowy",
    "sunny": "sunny",
    "windy": "windy",
    "windy-variant": "windy",
    "exceptional": "stormy",
}


def _map_weather(state: str) -> str | None:
    key = str(state or "").strip().lower()
    return _WEATHER_MAP.get(key)


def _pick_weather(states: list[dict]) -> dict[str, Any]:
    rows = [
        st for st in states
        if str(st.get("entity_id") or "").startswith("weather.")
        and str(st.get("state") or "").lower() not in {"unavailable", "unknown", ""}
    ]
    if not rows:
        return {}
    # Prefer entities that look like a home forecast (name hints), else first.
    ranked = sorted(
        rows,
        key=lambda st: (
            0 if "home" in str(st.get("entity_id") or "") else 1,
            0 if "forecast" not in str(st.get("entity_id") or "") else 1,
            str(st.get("entity_id") or ""),
        ),
    )
    st = ranked[0]
    attrs = st.get("attributes") or {}
    tag = _map_weather(st.get("state") or "")
    out: dict[str, Any] = {}
    if tag:
        out["weather"] = tag
    temp = attrs.get("temperature")
    if isinstance(temp, (int, float)):
        out["temp"] = float(temp)
    unit = attrs.get("temperature_unit") or attrs.get("unit_of_measurement")
    if unit:
        out["temp_unit"] = str(unit)
    return out


async def snapshot() -> dict[str, Any]:
    """Return cached weather snapshot for chat greetings. Never raises."""
    now = time.time()
    cached = _CACHE.get("payload")
    if cached is not None and (now - float(_CACHE.get("ts") or 0)) < _CACHE_TTL:
        return dict(cached)

    payload: dict[str, Any] = {}
    try:
        from services import homeassistant as ha
    except Exception as exc:
        log.debug("atmosphere ha import failed: %s", exc)
        _CACHE["payload"] = payload
        _CACHE["ts"] = now
        return dict(payload)

    if not ha.is_available():
        _CACHE["payload"] = payload
        _CACHE["ts"] = now
        return dict(payload)

    try:
        states = await ha._fetch_states_cached()  # noqa: SLF001 — shared HA cache
        if isinstance(states, list):
            payload.update(_pick_weather(states))
    except Exception as exc:
        log.debug("atmosphere weather lookup failed: %s", exc)

    _CACHE["payload"] = payload
    _CACHE["ts"] = now
    return dict(payload)
