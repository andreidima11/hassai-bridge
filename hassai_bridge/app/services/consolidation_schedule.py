"""Auto memory-consolidation schedule helpers."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any


SCHEDULES = ("daily", "weekly", "interval")


def normalize_auto_consolidation(raw: Any) -> dict:
    """Return a full auto_consolidation config with sane bounds."""
    src = raw if isinstance(raw, dict) else {}
    schedule = str(src.get("schedule") or "daily").strip().lower()
    if schedule not in SCHEDULES:
        schedule = "daily"
    try:
        hour = int(src.get("hour", 3))
    except (TypeError, ValueError):
        hour = 3
    hour = max(0, min(23, hour))
    try:
        interval_hours = int(src.get("interval_hours", 6))
    except (TypeError, ValueError):
        interval_hours = 6
    interval_hours = max(1, min(168, interval_hours))
    try:
        last_run_at = float(src.get("last_run_at") or 0)
    except (TypeError, ValueError):
        last_run_at = 0.0
    return {
        "enabled": bool(src.get("enabled", False)),
        "schedule": schedule,
        "hour": hour,
        "interval_hours": interval_hours,
        "last_run_at": last_run_at,
    }


def should_run_now(
    ac: dict,
    *,
    now: datetime | None = None,
    last_daily_key: str | None = None,
    wall_time: float | None = None,
) -> tuple[bool, str | None]:
    """Decide if consolidation should run.

    Returns (should_run, new_daily_key).
    For daily/weekly, new_daily_key is YYYY-MM-DD when a run fires (caller stores it).
    For interval, new_daily_key is None (caller updates last_run_at).
    """
    cfg = normalize_auto_consolidation(ac)
    if not cfg["enabled"]:
        return False, last_daily_key

    now = now or datetime.now()
    wall = wall_time if wall_time is not None else time.time()
    schedule = cfg["schedule"]

    if schedule == "interval":
        due = wall - float(cfg["last_run_at"] or 0) >= cfg["interval_hours"] * 3600
        return due, last_daily_key

    if now.hour != cfg["hour"]:
        return False, last_daily_key

    run_key = now.strftime("%Y-%m-%d")
    if schedule == "weekly" and now.weekday() != 0:
        return False, last_daily_key
    if run_key == last_daily_key:
        return False, last_daily_key
    return True, run_key


def format_status(ac: dict, *, lang: str = "en") -> str:
    cfg = normalize_auto_consolidation(ac)
    if lang == "ro":
        if not cfg["enabled"]:
            return "dezactivată"
        if cfg["schedule"] == "interval":
            return f"activă — la fiecare {cfg['interval_hours']}h"
        if cfg["schedule"] == "weekly":
            return f"activă — săptămânal (luni) la ora {cfg['hour']:02d}:00"
        return f"activă — zilnic la ora {cfg['hour']:02d}:00"
    if not cfg["enabled"]:
        return "off"
    if cfg["schedule"] == "interval":
        return f"on — every {cfg['interval_hours']}h"
    if cfg["schedule"] == "weekly":
        return f"on — weekly (Monday) at {cfg['hour']:02d}:00"
    return f"on — daily at {cfg['hour']:02d}:00"
