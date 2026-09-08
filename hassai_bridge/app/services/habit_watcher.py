"""Learn frequent manual device toggles from HA logbook + entity intelligence."""

from __future__ import annotations

import asyncio
import json
import logging
import re
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

_BULB_NAME_RE = re.compile(
    r"(?:#\s*\d+|bec\s*\d+|bulb\s*\d+|channel\s*\d+|led\s*\d+|\bbec\b|\bbulb\b)",
    re.I,
)
_GROUPISH_NAME_RE = re.compile(
    r"(ambient|ambientale|group|grup|scene|seara|evening|all\b|toate|lumini\b)",
    re.I,
)
_GATEISH_RE = re.compile(r"(poart|gate|garage|garaj|portal|barrier|pieton)", re.I)
_LIGHTISH_RE = re.compile(r"(lumin|light|bec|bulb|led|lamp|ilumin)", re.I)
_ACTIONABLE_PREFIXES = ("light.", "switch.", "cover.", "scene.", "climate.")
_HELPER_PREFIXES = (
    "input_boolean.", "input_number.", "input_text.", "input_select.",
    "input_datetime.", "binary_sensor.", "sensor.", "number.", "button.",
    "event.", "person.", "zone.",
)
_CONTACT_CLASSES = frozenset({"door", "garage_door", "opening", "window", "gate"})


def enabled(cfg: dict | None = None) -> bool:
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    rec = cfg.get("recommendations") if isinstance(cfg.get("recommendations"), dict) else {}
    if not isinstance(rec, dict):
        return True
    if rec.get("enabled") is False:
        return False
    mode = str(rec.get("mode") or "medium").strip().lower()
    return mode not in {"none", "off", "disabled"}


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


def _is_manual(entry: dict) -> bool:
    ctx_user = entry.get("context_user_id")
    ctx_parent = entry.get("context_parent_id")
    if ctx_parent and not ctx_user:
        return False
    return True


def _event_kind(entry: dict) -> str | None:
    """Return open|close|on|off for a logbook entry, or None."""
    state = str(entry.get("state") or entry.get("new_state") or "").lower()
    msg = str(entry.get("message") or "").lower()
    if state in {"on", "home"} or "turned on" in msg or "turned_on" in msg:
        return "on"
    if state in {"off"} or "turned off" in msg or "turned_off" in msg:
        return "off"
    if state in {"open", "opening"} or "opened" in msg or "opening" in msg:
        return "open"
    if state in {"closed", "closing"} or "closed" in msg or "closing" in msg:
        return "close"
    return None


def _member_ids(attrs: dict) -> list[str]:
    raw = attrs.get("entity_id")
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def classify_light_kind(
    entity_id: str,
    *,
    attrs: dict | None = None,
    platform: str = "",
    name: str = "",
) -> str:
    """Classify light/switch as group vs leaf bulb."""
    attrs = attrs if isinstance(attrs, dict) else {}
    members = _member_ids(attrs)
    plat = str(platform or "").lower()
    label = f"{name} {entity_id}"
    if members and len(members) >= 2:
        return "group"
    if plat in {"group", "light_group", "adaptive_lighting"}:
        return "group"
    if _GROUPISH_NAME_RE.search(label) and not _BULB_NAME_RE.search(label):
        return "group"
    if _BULB_NAME_RE.search(label):
        return "bulb"
    if entity_id.startswith("switch."):
        return "switch"
    return "bulb" if members else "light"


def looks_like_bulb_name(name: str, entity_id: str = "") -> bool:
    return bool(_BULB_NAME_RE.search(f"{name} {entity_id}"))


def is_actionable_entity(entity_id: str) -> bool:
    eid = str(entity_id or "").lower()
    if not eid or eid.startswith(_HELPER_PREFIXES):
        return False
    return eid.startswith(_ACTIONABLE_PREFIXES)


def is_gateish(name: str = "", entity_id: str = "") -> bool:
    """Real gates/covers only — not lights or helpers named after a gate."""
    eid = str(entity_id or "").lower()
    name = str(name or "")
    if not eid or eid.startswith(_HELPER_PREFIXES) or eid.startswith("light."):
        return False
    blob = f"{name} {eid}"
    if not _GATEISH_RE.search(blob):
        return False
    # "Lumina poartă" is a light helper/name, not the gate actuator.
    if _LIGHTISH_RE.search(blob) and not eid.startswith("cover."):
        return False
    return eid.startswith(("cover.", "switch."))


def is_open_like(
    states: dict[str, dict] | None,
    entity_id: str,
    contact_id: str | None = None,
) -> bool:
    """True if a gate/cover looks open. Prefer contact; else switch on/off or cover state."""
    states = states or {}
    if contact_id:
        cst = states.get(contact_id) or {}
        cstate = str(cst.get("state") or "").lower()
        # HA door/garage contact: on usually means open/detected.
        if cstate in {"on", "open"}:
            return True
        if cstate in {"off", "closed"}:
            return False
    st = states.get(entity_id) or {}
    state = str(st.get("state") or "").lower()
    if state in {"open", "opening", "on"}:
        return True
    if state in {"closed", "closing", "off"}:
        return False
    return False


def _period_buckets() -> dict[str, dict[str, int]]:
    return {
        "morning": defaultdict(int),
        "day": defaultdict(int),
        "evening": defaultdict(int),
        "night": defaultdict(int),
    }


def _entry_period(entry: dict) -> str:
    when = entry.get("when") or entry.get("last_changed") or ""
    try:
        if isinstance(when, (int, float)):
            dt = datetime.fromtimestamp(float(when), tz=timezone.utc).astimezone()
        else:
            dt = datetime.fromisoformat(str(when).replace("Z", "+00:00")).astimezone()
        return _period_for_hour(dt.hour)
    except Exception:
        return current_period()


def build_group_index(states_by_id: dict[str, dict]) -> dict[str, str]:
    """Map leaf entity_id → preferred parent group entity_id."""
    child_to_parents: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for eid, st in states_by_id.items():
        if not (eid.startswith("light.") or eid.startswith("switch.") or eid.startswith("group.")):
            continue
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        name = str(attrs.get("friendly_name") or "")
        members = _member_ids(attrs)
        if len(members) < 2:
            continue
        # Prefer larger groups and ambient-named parents.
        bonus = 10 if _GROUPISH_NAME_RE.search(name) else 0
        score = len(members) + bonus
        for mid in members:
            child_to_parents[mid].append((score, eid))
    out: dict[str, str] = {}
    for child, parents in child_to_parents.items():
        parents.sort(key=lambda x: x[0], reverse=True)
        out[child] = parents[0][1]
    return out


def pair_contacts(
    states_by_id: dict[str, dict],
    *,
    registry: dict[str, dict] | None = None,
) -> dict[str, str]:
    """Map cover/switch entity_id → binary_sensor contact entity_id."""
    registry = registry or {}
    contacts: list[tuple[str, str, str, str]] = []  # eid, device_id, area_id, name
    actuators: list[tuple[str, str, str, str]] = []

    for eid, st in states_by_id.items():
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        reg = registry.get(eid) or {}
        device_id = str(reg.get("device_id") or "")
        area_id = str(reg.get("area_id") or attrs.get("area_id") or "")
        name = str(attrs.get("friendly_name") or eid)
        if eid.startswith("binary_sensor."):
            dc = str(attrs.get("device_class") or "").lower()
            if dc in _CONTACT_CLASSES or _GATEISH_RE.search(name) or _GATEISH_RE.search(eid):
                contacts.append((eid, device_id, area_id, name))
        elif eid.startswith("cover.") or (
            eid.startswith("switch.") and is_gateish(name, eid)
        ):
            actuators.append((eid, device_id, area_id, name))

    pairs: dict[str, str] = {}
    used_contacts: set[str] = set()
    # Prefer same device_id, then same area + gateish name overlap.
    for act_eid, act_dev, act_area, act_name in actuators:
        best = None
        best_score = -1
        for c_eid, c_dev, c_area, c_name in contacts:
            if c_eid in used_contacts:
                continue
            score = 0
            if act_dev and c_dev and act_dev == c_dev:
                score += 100
            if act_area and c_area and act_area == c_area:
                score += 40
            if _GATEISH_RE.search(act_name) and _GATEISH_RE.search(c_name):
                score += 20
            # Token overlap on entity object part
            a_tok = set(re.findall(r"[a-z0-9]+", act_eid.split(".", 1)[-1].lower()))
            c_tok = set(re.findall(r"[a-z0-9]+", c_eid.split(".", 1)[-1].lower()))
            score += 5 * len(a_tok & c_tok)
            if score > best_score:
                best_score = score
                best = c_eid
        if best and best_score >= 20:
            pairs[act_eid] = best
            used_contacts.add(best)
    return pairs


def enrich_meta(
    states_by_id: dict[str, dict],
    *,
    registry: dict[str, dict] | None = None,
    area_labels: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Per-entity kind/area/parent/contact metadata."""
    registry = registry or {}
    area_labels = area_labels or {}
    child_to_parent = build_group_index(states_by_id)
    contacts = pair_contacts(states_by_id, registry=registry)
    meta: dict[str, dict] = {}

    for eid, st in states_by_id.items():
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        reg = registry.get(eid) or {}
        name = str(attrs.get("friendly_name") or reg.get("name") or eid)
        area_id = str(reg.get("area_id") or "") or None
        device_id = str(reg.get("device_id") or "") or None
        platform = str(reg.get("platform") or "")
        domain = eid.split(".", 1)[0]
        row = {
            "entity_id": eid,
            "name": name,
            "domain": domain,
            "area_id": area_id,
            "area_name": area_labels.get(area_id or "", "") if area_id else "",
            "device_id": device_id,
            "platform": platform,
            "member_ids": _member_ids(attrs),
            "parent_group_id": child_to_parent.get(eid),
            "contact_entity_id": contacts.get(eid),
            "kind": "other",
        }
        if domain in {"light", "switch"}:
            row["kind"] = classify_light_kind(
                eid, attrs=attrs, platform=platform, name=name
            )
            # Name/entity hints alone are enough — contact pairing is optional.
            if domain == "switch" and (
                contacts.get(eid) or is_gateish(name, eid)
            ):
                row["kind"] = "gate_switch"
        elif domain == "cover":
            row["kind"] = "cover"
        elif domain == "binary_sensor":
            dc = str(attrs.get("device_class") or "").lower()
            row["kind"] = "contact" if dc in _CONTACT_CLASSES or eid in contacts.values() else "sensor"
        elif domain == "scene":
            row["kind"] = "scene"
        meta[eid] = row
    return meta


def score_logbook(
    entries: list[dict],
    *,
    states: list[dict] | None = None,
    registry: dict[str, dict] | None = None,
    area_labels: dict[str, str] | None = None,
) -> dict:
    """Aggregate manual toggles for lights/switches/covers with entity intelligence."""
    states_by_id = {
        str(s.get("entity_id") or ""): s
        for s in (states or [])
        if isinstance(s, dict) and s.get("entity_id")
    }
    meta = enrich_meta(states_by_id, registry=registry, area_labels=area_labels)

    light_on: dict[str, int] = defaultdict(int)
    light_periods = _period_buckets()
    cover_open: dict[str, int] = defaultdict(int)
    cover_close: dict[str, int] = defaultdict(int)
    cover_periods = _period_buckets()
    names: dict[str, str] = {}

    for entry in entries or []:
        if not isinstance(entry, dict) or not _is_manual(entry):
            continue
        eid = str(entry.get("entity_id") or "").strip()
        if not eid or not is_actionable_entity(eid):
            continue
        kind = _event_kind(entry)
        if not kind:
            continue
        period = _entry_period(entry)
        if eid not in names:
            names[eid] = _friendly_name(states_by_id, eid, str(entry.get("name") or ""))

        if eid.startswith("light.") or eid.startswith("switch."):
            info = meta.get(eid) or {}
            display = names.get(eid) or info.get("name") or eid
            # Gates / barriers never count as lights — even without a paired contact.
            if (
                info.get("kind") == "gate_switch"
                or info.get("contact_entity_id")
                or is_gateish(display, eid)
            ):
                if kind in {"on", "open"}:
                    cover_open[eid] += 1
                    cover_periods[period][eid] += 1
                elif kind in {"off", "close"}:
                    cover_close[eid] += 1
                    cover_periods[period][eid] += 1
                continue
            if kind != "on":
                continue
            # Only roll "bec 1" leaves into the parent group. Named lamps the
            # user toggles themselves (LED pat, Lampa dormitor 1) keep their own score.
            target = eid
            if looks_like_bulb_name(names.get(eid, ""), eid) and info.get("parent_group_id"):
                target = info["parent_group_id"]
                if target not in names:
                    names[target] = _friendly_name(states_by_id, target)
            light_on[target] += 1
            light_periods[period][target] += 1
        elif eid.startswith("cover."):
            if kind in {"open", "on"}:
                cover_open[eid] += 1
                cover_periods[period][eid] += 1
            elif kind in {"close", "off"}:
                cover_close[eid] += 1
                cover_periods[period][eid] += 1

    lights = []
    for eid, count in sorted(light_on.items(), key=lambda kv: kv[1], reverse=True)[:20]:
        info = meta.get(eid) or {}
        name = names.get(eid) or info.get("name") or eid
        if is_gateish(name, eid) or info.get("kind") == "gate_switch":
            # Belts and suspenders: never emit gates into lights[].
            cover_open.setdefault(eid, 0)
            cover_open[eid] = max(int(cover_open.get(eid) or 0), count)
            for p in ("morning", "day", "evening", "night"):
                cover_periods[p][eid] = max(
                    int(cover_periods[p].get(eid) or 0),
                    int(light_periods[p].get(eid) or 0),
                )
            continue
        lights.append({
            "entity_id": eid,
            "name": name,
            "count": count,
            "periods": {
                p: int(light_periods[p].get(eid) or 0)
                for p in ("morning", "day", "evening", "night")
            },
            "kind": info.get("kind") or "light",
            "area_id": info.get("area_id"),
            "area_name": info.get("area_name") or "",
            "parent_group_id": info.get("parent_group_id"),
            "member_ids": info.get("member_ids") or [],
            "platform": info.get("platform") or "",
        })

    # Also promote gateish switches from states that never toggled "on" in window
    # but appear frequently as off/close or exist with contact.
    for eid, info in meta.items():
        if not is_actionable_entity(eid):
            continue
        if info.get("kind") != "gate_switch" and not is_gateish(info.get("name") or "", eid):
            continue
        if eid in cover_open or eid in cover_close:
            continue
        cover_open[eid] = 1
        if eid not in names:
            names[eid] = info.get("name") or eid

    covers = []
    cover_ids = set(cover_open) | set(cover_close)
    ranked = sorted(
        cover_ids,
        key=lambda e: cover_open.get(e, 0) + cover_close.get(e, 0),
        reverse=True,
    )[:15]
    for eid in ranked:
        info = meta.get(eid) or {}
        covers.append({
            "entity_id": eid,
            "name": names.get(eid) or info.get("name") or eid,
            "open_count": int(cover_open.get(eid) or 0),
            "close_count": int(cover_close.get(eid) or 0),
            "periods": {
                p: int(cover_periods[p].get(eid) or 0)
                for p in ("morning", "day", "evening", "night")
            },
            "kind": info.get("kind") or "cover",
            "area_id": info.get("area_id"),
            "area_name": info.get("area_name") or "",
            "contact_entity_id": info.get("contact_entity_id"),
        })

    # Scene hints by name match to areas (activation not always in logbook well).
    scenes = []
    for eid, st in states_by_id.items():
        if not eid.startswith("scene."):
            continue
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        name = str(attrs.get("friendly_name") or eid)
        if not _GROUPISH_NAME_RE.search(name) and "seara" not in name.lower() and "evening" not in name.lower():
            continue
        info = meta.get(eid) or {}
        scenes.append({
            "entity_id": eid,
            "name": name,
            "area_id": info.get("area_id"),
            "area_name": info.get("area_name") or "",
        })
        if len(scenes) >= 20:
            break

    return {
        "updated_at": time.time(),
        "lookback_days": _LOOKBACK_DAYS,
        "lights": lights,
        "covers": covers,
        "scenes": scenes,
        "meta_version": 6,
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
            from services import entity_tools as et

            entries = await _fetch_logbook_raw()
            states = await ha._fetch_states_cached()  # noqa: SLF001
            registry: dict[str, dict] = {}
            area_labels: dict[str, str] = {}
            try:
                entities, areas, _devices, _labels, *_ = await ha._fetch_registry_bundle()  # noqa: SLF001
                registry = et.registry_by_entity_id(entities)
                area_labels, _ = et.index_areas(areas)
            except Exception as e:
                log.debug("registry enrichment skipped: %s", e)
            data = score_logbook(
                entries,
                states=states,
                registry=registry,
                area_labels=area_labels,
            )
            save_habits(data)
            _last_refresh = time.time()
            log.info(
                "Habits refreshed: %s lights, %s covers",
                len(data.get("lights") or []),
                len(data.get("covers") or []),
            )
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
    if int(data.get("meta_version") or 0) < 6:
        return True
    return (time.time() - updated) >= _REFRESH_INTERVAL_S


def _normalize_cover_rows(habits: dict) -> list[dict]:
    """Covers from habits plus any gateish rows wrongly stored under lights."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in list(habits.get("covers") or []) + list(habits.get("lights") or []):
        if not isinstance(row, dict):
            continue
        eid = str(row.get("entity_id") or "")
        name = str(row.get("name") or "")
        if not eid:
            continue
        is_cover = eid.startswith("cover.") or row.get("kind") in {"cover", "gate_switch"}
        if not is_cover and not is_gateish(name, eid):
            continue
        if not is_actionable_entity(eid):
            continue
        if eid in seen:
            continue
        seen.add(eid)
        periods = row.get("periods") if isinstance(row.get("periods"), dict) else {}
        out.append({
            "entity_id": eid,
            "name": name or eid,
            "open_count": int(row.get("open_count") or row.get("count") or 0),
            "close_count": int(row.get("close_count") or 0),
            "periods": periods,
            "kind": row.get("kind") or "gate_switch",
            "area_id": row.get("area_id"),
            "area_name": row.get("area_name") or "",
            "contact_entity_id": row.get("contact_entity_id"),
        })
    return out


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
        eid = str(row.get("entity_id") or "")
        name = str(row.get("name") or "")
        if is_gateish(name, eid) or row.get("kind") in {"gate_switch", "cover"}:
            continue
        # Prefer groups over leaf bulbs.
        kind = str(row.get("kind") or "")
        if kind == "bulb" and looks_like_bulb_name(name, eid):
            # Demote explicit bulbs hard unless no group alternative later.
            bulb_penalty = 8
        elif kind in {"group", "light"} and (row.get("member_ids") or kind == "group"):
            bulb_penalty = -6
        else:
            bulb_penalty = 0
        periods = row.get("periods") if isinstance(row.get("periods"), dict) else {}
        score = int(periods.get(period) or 0) * 3 + int(row.get("count") or 0) - bulb_penalty
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    # Drop "bec 1" leaves when a parent group is already in the ranking.
    out: list[dict] = []
    for score, row in scored:
        if score <= 0:
            continue
        eid = str(row.get("entity_id") or "")
        name = str(row.get("name") or "")
        if looks_like_bulb_name(name, eid):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def top_covers_for_period(
    habits: dict | None = None,
    *,
    period: str | None = None,
    limit: int = 3,
) -> list[dict]:
    habits = habits or load_habits()
    period = period or current_period()
    covers = _normalize_cover_rows(habits)
    scored = []
    for row in covers:
        periods = row.get("periods") if isinstance(row.get("periods"), dict) else {}
        total = int(row.get("open_count") or 0) + int(row.get("close_count") or 0)
        score = int(periods.get(period) or 0) * 3 + total
        # Name-matched gates still surface even with thin logbook counts.
        if score <= 0 and is_gateish(str(row.get("name") or ""), str(row.get("entity_id") or "")):
            score = 1
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
