"""Tests for auto memory-consolidation schedule helpers."""

from datetime import datetime

from services.consolidation_schedule import (
    format_status,
    normalize_auto_consolidation,
    should_run_now,
)


def test_normalize_defaults_and_bounds():
    assert normalize_auto_consolidation(None) == {
        "enabled": False,
        "schedule": "daily",
        "hour": 3,
        "interval_hours": 6,
        "last_run_at": 0.0,
    }
    n = normalize_auto_consolidation(
        {"schedule": "interval", "hour": 99, "interval_hours": 999, "enabled": 1},
    )
    assert n["schedule"] == "interval"
    assert n["hour"] == 23
    assert n["interval_hours"] == 168
    assert n["enabled"] is True


def test_daily_runs_once_per_day_at_hour():
    ac = {"enabled": True, "schedule": "daily", "hour": 3}
    due, key = should_run_now(
        ac, now=datetime(2026, 3, 15, 3, 10), last_daily_key=None,
    )
    assert due is True
    assert key == "2026-03-15"

    due2, _ = should_run_now(
        ac, now=datetime(2026, 3, 15, 3, 40), last_daily_key=key,
    )
    assert due2 is False

    due3, _ = should_run_now(
        ac, now=datetime(2026, 3, 15, 4, 0), last_daily_key=None,
    )
    assert due3 is False


def test_weekly_only_monday():
    ac = {"enabled": True, "schedule": "weekly", "hour": 3}
    # 2026-03-16 is Monday
    due_mon, key = should_run_now(
        ac, now=datetime(2026, 3, 16, 3, 0), last_daily_key=None,
    )
    assert due_mon is True
    assert key == "2026-03-16"
    # Tuesday
    due_tue, _ = should_run_now(
        ac, now=datetime(2026, 3, 17, 3, 0), last_daily_key=None,
    )
    assert due_tue is False


def test_interval_uses_last_run_at():
    ac = {
        "enabled": True,
        "schedule": "interval",
        "interval_hours": 6,
        "last_run_at": 1_000_000.0,
    }
    due_soon, key = should_run_now(ac, wall_time=1_000_000 + 5 * 3600)
    assert due_soon is False
    assert key is None

    due_later, key2 = should_run_now(ac, wall_time=1_000_000 + 6 * 3600)
    assert due_later is True
    assert key2 is None


def test_disabled_never_runs():
    due, _ = should_run_now(
        {"enabled": False, "schedule": "interval", "interval_hours": 1, "last_run_at": 0},
        wall_time=10_000,
    )
    assert due is False


def test_format_status_en_ro():
    assert "off" in format_status({"enabled": False}, lang="en")
    assert "dezactivată" in format_status({"enabled": False}, lang="ro")
    assert "every 6h" in format_status(
        {"enabled": True, "schedule": "interval", "interval_hours": 6}, lang="en",
    )
    assert "la fiecare 6h" in format_status(
        {"enabled": True, "schedule": "interval", "interval_hours": 6}, lang="ro",
    )
