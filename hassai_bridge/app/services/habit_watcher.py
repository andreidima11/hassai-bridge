"""Learn frequent manual light/switch toggles from HA logbook."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.config import DATA_DIR, load_config

log = logging.getLogger("hassai.habits")

HABITS_FILE = DATA_DIR / "habits.json"
_REFRESH_INTERVAL_S = 45 * 60
_LOOKBACK_DAYS = 10
_lock = asyncio.Lock()
_last_refresh = 0.0


def enabled(cfg: dict | None = None) -> bool:
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    rec = cfg.get("recommendations") if isinstance(cfg.get("recommendations"), dict) else {}
    if isinstance(rec, dict) and rec:
        return rec.get("enabled") is not False
    return True


def _period_for_hour(hour: int) -> str:
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "day"
    if 17 <= hour < 23:
        return "evening"
    return "night"


def current_period(now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    return _period_for_hour(now.hour)


def load_habits() -> dict:
    try:
        raw = HABITS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.debug("habits load failed: %s", e)
        return {}


def save_habits(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HABITS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HABITS_FILE)


def _friendly_name(states_by_id: dict[str, dict], entity_id: str, fallback: str = "") -> str:
    st = states_by_id.get(entity_id) or {}
    attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
    name = str(attrs.get("friendly_name") or "").strip()
    if name:
        return name
    return fallback or entity_id.split(".", 1)[-1].replace("_", " ").title()


def _is_manual_on(entry: dict) -> bool:
    """Prefer UI/manual toggles; skip clear automation children when possible."""
    state = str(entry.get("state") or entry.get("new_state") or "").lower()
    msg = str(entry.get("message") or "").lower()
    is_on = state in {"on", "home", "open"} or "turned on" in msg or "turned_on" in msg
    if not is_on:
        return False
    ctx_user = entry.get("context_user_id")
    ctx_parent = entry.get("context_parent_id")
    if ctx_parent and not ctx_user:
        return False
    return True


def score_logbook(
    entries: list[dict],
    *,
    states: list[dict] | None = None,
) -> dict:
    """Aggregate manual on-toggles for light.* / switch.*."""
    states_by_id = {
        str(s.get("entity_id") or ""): s
        for s in (states or [])
        if isinstance(s, dict) and s.get("entity_id")
    }
    totals: dict[str, int] = defaultdict(int)
    by_period: dict[str, dict[str, int]] = {
        "morning": defaultdict(int),
        "day": defaultdict(int),
        "evening": defaultdict(int),
        "night": defaultdict(int),
    }
    names: dict[str, str] = {}

    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("entity_id") or "").strip()
        if not eid or not (eid.startswith("light.") or eid.startswith("switch.")):
            continue
        if not _is_manual_on(entry):
            continue
        when = entry.get("when") or entry.get("last_changed") or ""
        try:
            if isinstance(when, (int, float)):
                dt = datetime.fromtimestamp(float(when), tz=timezone.utc).astimezone()
            else:
                dt = datetime.fromisoformat(str(when).replace("Z", "+00:00")).astimezone()
            period = _period_for_hour(dt.hour)
        except Exception:
            period = current_period()
        totals[eid] += 1
        by_period[period][eid] += 1
        if eid not in names:
            names[eid] = _friendly_name(states_by_id, eid, str(entry.get("name") or ""))

    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:20]
    lights = []
    for eid, count in top:
        lights.append({
            "entity_id": eid,
            "name": names.get(eid) or eid,
            "count": count,
            "periods": {
                p: int(by_period[p].get(eid) or 0)
                for p in ("morning", "day", "evening", "night")
            },
        })
    return {
        "updated_at": time.time(),
        "lookback_days": _LOOKBACK_DAYS,
        "lights": lights,
    }


async def _fetch_logbook_raw(days: int = _LOOKBACK_DAYS) -> list[dict]:
    from services import homeassistant as ha

    start = datetime.now(timezone.utc) - timedelta(days=days)
    payload = await ha._core_query(  # noqa: SLF001 — shared supervisor core API
        f"/logbook/{start.isoformat()}",
        {"period": max(1, days)},
    )
    return payload if isinstance(payload, list) else []


async def refresh_habits(*, force: bool = False) -> dict:
    """Refresh habits from HA; no-op when recommendations disabled."""
    global _last_refresh
    cfg = load_config()
    if not enabled(cfg):
        return load_habits()
    now = time.time()
    if not force and _last_refresh and (now - _last_refresh) < 120:
        return load_habits()
    async with _lock:
        now = time.time()
        if not force and _last_refresh and (now - _last_refresh) < 120:
            return load_habits()
        try:
            from services import homeassistant as ha

            entries = await _fetch_logbook_raw()
            states = await ha._fetch_states_cached()  # noqa: SLF001
            data = score_logbook(entries, states=states)
            save_habits(data)
            _last_refresh = time.time()
            log.info("Habits refreshed: %s light/switch favorites", len(data.get("lights") or []))
            return data
        except Exception as e:
            log.warning("Habit refresh failed: %s", e)
            return load_habits()


def needs_refresh(cfg: dict | None = None) -> bool:
    if not enabled(cfg):
        return False
    data = load_habits()
    updated = float(data.get("updated_at") or 0)
    if not updated:
        return True
    return (time.time() - updated) >= _REFRESH_INTERVAL_S


def top_lights_for_period(
    habits: dict | None = None,
    *,
    period: str | None = None,
    limit: int = 5,
) -> list[dict]:
    habits = habits or load_habits()
    period = period or current_period()
    lights = list(habits.get("lights") or [])
    scored = []
    for row in lights:
        periods = row.get("periods") if isinstance(row.get("periods"), dict) else {}
        score = int(periods.get(period) or 0) * 3 + int(row.get("count") or 0)
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for s, r in scored if s > 0][:limit]


async def habit_loop():
    """Background refresh every ~45 minutes when enabled."""
    await asyncio.sleep(35)
    while True:
        try:
            cfg = load_config()
            if enabled(cfg) and needs_refresh(cfg):
                await refresh_habits()
            await asyncio.sleep(900)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Habit loop error: %s", e)
            await asyncio.sleep(600)
