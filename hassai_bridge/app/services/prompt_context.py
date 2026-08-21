"""Volatile prompt snippets (time, etc.) injected per chat turn."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("hassai.prompt_context")

_HA_CORE_CONFIG = Path("/config/.storage/core.config")


@lru_cache(maxsize=1)
def _ha_timezone_from_storage() -> str:
    """Read Home Assistant time_zone once (file rarely changes)."""
    try:
        if not _HA_CORE_CONFIG.is_file():
            return ""
        raw = json.loads(_HA_CORE_CONFIG.read_text(encoding="utf-8"))
        data = raw.get("data") if isinstance(raw, dict) else None
        tz = ""
        if isinstance(data, dict):
            tz = str(data.get("time_zone") or data.get("timezone") or "").strip()
        return tz
    except Exception as e:
        log.debug("Could not read HA time_zone: %s", e)
        return ""


def resolve_local_timezone_name() -> str:
    """Prefer HA config timezone, then TZ env, else empty (system local)."""
    for candidate in (_ha_timezone_from_storage(), os.environ.get("TZ", "").strip()):
        if candidate:
            return candidate
    return ""


def local_now() -> datetime:
    name = resolve_local_timezone_name()
    if name:
        try:
            return datetime.now(ZoneInfo(name))
        except ZoneInfoNotFoundError:
            log.warning("Unknown timezone %r — falling back to system local", name)
    return datetime.now().astimezone()


def current_datetime_context(now: datetime | None = None) -> str:
    """Tell the model what 'today' is — volatile (not KV-cache stable)."""
    dt = now or local_now()
    tz_label = dt.tzname() or resolve_local_timezone_name() or "local"
    # Monday, August 21, 2026 13:45 (2026-08-21T13:45+03:00, Europe/Bucharest)
    nice = dt.strftime("%A, %B %d, %Y %H:%M").replace(" 0", " ")
    iso = dt.isoformat(timespec="minutes")
    offset = dt.strftime("%z")
    if offset and len(offset) >= 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return (
        "[Current time]\n"
        f"Right now it is {nice} "
        f"({iso}, timezone {tz_label}"
        f"{f', UTC{offset}' if offset else ''}). "
        "Treat this as the authoritative current date and time for this reply "
        "(day of week, calendar date, and clock). "
        "Do not claim you lack access to the current date."
    )


def clear_timezone_cache() -> None:
    _ha_timezone_from_storage.cache_clear()
