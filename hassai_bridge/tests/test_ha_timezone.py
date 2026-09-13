"""Home Assistant timezone helpers for prompt clock context."""

from __future__ import annotations

from datetime import datetime, timezone

from services import homeassistant as ha


def test_ha_local_now_uses_iana_zone(monkeypatch):
    monkeypatch.setitem(ha._TZ_CACHE, "tz", "Europe/Bucharest")
    monkeypatch.setitem(ha._TZ_CACHE, "ts", 1e18)
    now = ha.ha_local_now("Europe/Bucharest")
    assert str(now.tzinfo) == "Europe/Bucharest" or getattr(now.tzinfo, "key", None) == "Europe/Bucharest"


def test_format_ha_local_converts_utc():
    utc = datetime(2026, 9, 13, 0, 30, tzinfo=timezone.utc)
    text = ha.format_ha_local(utc, tz_name="Europe/Bucharest")
    # Bucharest is UTC+3 in September
    assert "03:30" in text
    assert "Europe/Bucharest" in text


def test_format_ha_local_falls_back_utc():
    utc = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    text = ha.format_ha_local(utc, tz_name="Not/AZone")
    assert "12:00" in text
    assert "UTC" in text
