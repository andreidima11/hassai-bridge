from datetime import datetime
from zoneinfo import ZoneInfo

from services import prompt_context as pctx


def test_current_datetime_context_includes_weekday_and_iso(monkeypatch):
    fixed = datetime(2026, 8, 21, 13, 45, tzinfo=ZoneInfo("Europe/Bucharest"))
    monkeypatch.setattr(pctx, "local_now", lambda: fixed)
    monkeypatch.setattr(pctx, "resolve_local_timezone_name", lambda: "Europe/Bucharest")
    text = pctx.current_datetime_context()
    assert "[Current time]" in text
    assert "Friday" in text
    assert "August 21, 2026" in text
    assert "13:45" in text
    assert "2026-08-21T13:45" in text
    assert "Do not claim you lack access to the current date" in text


def test_local_now_uses_tz_env(monkeypatch, tmp_path):
    pctx.clear_timezone_cache()
    monkeypatch.setenv("TZ", "Europe/Bucharest")
    monkeypatch.setattr(pctx, "_HA_CORE_CONFIG", tmp_path / "missing")
    pctx.clear_timezone_cache()
    now = pctx.local_now()
    assert str(now.tzinfo) == "Europe/Bucharest" or now.tzname() in ("EET", "EEST", "Europe/Bucharest")


def test_ha_timezone_from_storage(monkeypatch, tmp_path):
    cfg = tmp_path / "core.config"
    cfg.write_text(
        '{"data": {"time_zone": "Europe/Bucharest", "location_name": "Home"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(pctx, "_HA_CORE_CONFIG", cfg)
    pctx.clear_timezone_cache()
    assert pctx._ha_timezone_from_storage() == "Europe/Bucharest"
    assert pctx.resolve_local_timezone_name() == "Europe/Bucharest"
