"""Build empty-chat and follow-up recommendation chips."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date

from core.config import load_config
from services import habit_watcher as hw
from services import recs_llm as rl

log = logging.getLogger("hassai.recommendations")

_I18N = {
    "en": {
        "turn_on": "Turn on {name}",
        "turn_on_prompt": "Turn on {name}",
        "turn_off": "Turn off {name}",
        "turn_off_prompt": "Turn off {name}",
        "open": "Open {name}",
        "open_prompt": "Open {name}",
        "close": "Close {name}",
        "close_prompt": "Close {name}",
        "activate_scene": "Activate {name}",
        "activate_scene_prompt": "Activate scene {name}",
        "energy_today": "How much energy did I produce today?",
        "energy_prompt": "How much solar/energy did I produce today? Summarize from Home Assistant statistics if available.",
        "house_status": "Home status",
        "house_prompt": "Give me a short home status — lights on, doors/gates, climate, and solar if available.",
        "cameras": "What's on the cameras?",
        "cameras_prompt": "Check recent Frigate detections and tell me briefly what's going on.",
        "detail": "Tell me more",
        "detail_prompt": "Go into a bit more detail on that.",
        "usage_now": "What's using power now?",
        "usage_prompt": "What devices or sensors show high power usage right now?",
        "list_lights": "Which lights are on?",
        "list_lights_prompt": "List which lights are currently on.",
        "weather": "What's the weather like?",
        "weather_prompt": "What's the weather like right now at home?",
        "also_same_area": "Also turn on {name}",
        "also_same_area_prompt": "Also turn on {name}",
        "yes": "Yes",
        "yes_prompt": "Yes",
        "no": "No",
        "no_prompt": "No",
        "ac_on": "Turn on {name}",
        "ac_on_prompt": "It's warm ({temp}°C). Turn on {name} to cool.",
        "heat_on": "Turn on {name}",
        "heat_on_prompt": "It's cool ({temp}°C). Turn on {name}.",
        "heat_raise": "Raise {name} to {target}°C",
        "heat_raise_prompt": "It's cool ({temp}°C). Set {name} to {target}°C.",
        "cool_lower": "Lower {name} to {target}°C",
        "cool_lower_prompt": "It's warm ({temp}°C). Set {name} to {target}°C.",
    },
    "ro": {
        "turn_on": "Aprinde {name}",
        "turn_on_prompt": "Aprinde {name}",
        "turn_off": "Stinge {name}",
        "turn_off_prompt": "Stinge {name}",
        "open": "Deschide {name}",
        "open_prompt": "Deschide {name}",
        "close": "Închide {name}",
        "close_prompt": "Închide {name}",
        "activate_scene": "Activează {name}",
        "activate_scene_prompt": "Activează scena {name}",
        "energy_today": "Cât curent am produs azi?",
        "energy_prompt": "Cât curent / energie solară am produs azi? Rezumat din statisticile Home Assistant dacă există.",
        "house_status": "Status casă",
        "house_prompt": "Dă-mi pe scurt statusul casei — lumini aprinse, uși/porți, climă și producție solară dacă există.",
        "cameras": "Ce e pe camere?",
        "cameras_prompt": "Verifică detecțiile recente Frigate și spune pe scurt ce se întâmplă.",
        "detail": "Mai multe detalii",
        "detail_prompt": "Detaliază puțin mai mult.",
        "usage_now": "Ce consumă acum?",
        "usage_prompt": "Ce dispozitive sau senzori arată consum mare acum?",
        "list_lights": "Ce lumini sunt aprinse?",
        "list_lights_prompt": "Listează luminile care sunt aprinse acum.",
        "weather": "Cum e vremea?",
        "weather_prompt": "Cum e vremea acum acasă?",
        "also_same_area": "Aprinde și {name}",
        "also_same_area_prompt": "Aprinde și {name}",
        "yes": "Da",
        "yes_prompt": "Da",
        "no": "Nu",
        "no_prompt": "Nu",
        "ac_on": "Pornește {name}",
        "ac_on_prompt": "E cald ({temp}°C). Pornește {name} pe răcire.",
        "heat_on": "Pornește {name}",
        "heat_on_prompt": "E răcoare ({temp}°C). Pornește {name}.",
        "heat_raise": "Crește {name} la {target}°C",
        "heat_raise_prompt": "E răcoare ({temp}°C). Setează {name} la {target}°C.",
        "cool_lower": "Scade {name} la {target}°C",
        "cool_lower_prompt": "E cald ({temp}°C). Setează {name} la {target}°C.",
    },
}

_SMALLTALK_RE = re.compile(
    r"^\s*(ce\s+faci|ce\s+mai\s+faci|salut|bun[aă]|hello|hi\b|hey\b|how\s+are\s+you|"
    r"ce\s+zici|ce\s+mai\s+zici|mulțumesc|multumesc|thanks|ok\b|bine\b)\s*[?.!]?\s*$",
    re.I,
)
_HA_TOPIC_RE = re.compile(
    r"\b(?:"
    r"lumin|bec|aprinde|stinge|switch|poart|gate|garaj|garage|cover|scen[aă]|climat|"
    r"temperatur|vreme|weather|camer[aă]|frigate|energie|energy|kwh|consum|solar|"
    r"status\s+cas|casa\b|home\s+assistant|\bha\b|senzor|alarm|uș[aă]|usa\b|door|"
    r"thermostat|smart\s*home|automatiz"
    r")\b",
    re.I,
)
_YESNO_RE = re.compile(
    r"(?:"
    r"\b(?:da\s+sau\s+nu|yes\s+or\s+no|agree|de\s+acord|confirmi|confirm|"
    r"vrei|vreți|vreti|poți|poti|putem|crezi|credeți|credeti|"
    r"should\s+(?:i|we)|do\s+you\s+(?:want|think|agree)|would\s+you|"
    r"are\s+you\s+(?:sure|ok|ready)|can\s+(?:i|we|you))\b"
    r".{0,120}\?\s*$"
    r")",
    re.I | re.S,
)
# Offers to dig deeper → prefer topic chips, not bare Da/Nu.
_OFFER_DETAIL_RE = re.compile(
    r"\b(?:"
    r"verific(?:a|ă)|detalia|mai\s+detaliat|în\s+detaliu|in\s+detaliu|"
    r"check\s+(?:something|anything|further|more)|more\s+detail|dig\s+deeper|"
    r"look\s+(?:into|at)\s+(?:something|anything|that)|anything\s+(?:else|specific)"
    r")\b",
    re.I,
)
# Topics mentioned in a status-style reply → contextual follow-up chips.
_TOPIC_CHIPS = (
    (re.compile(r"\binunda", re.I), {
        "id": "fu-topic-flood",
        "ro": ("Senzori inundație", "Verifică mai detaliat senzorii de inundație."),
        "en": ("Flood sensors", "Check the flood sensors in more detail."),
    }),
    (re.compile(r"\bbateri", re.I), {
        "id": "fu-topic-battery",
        "ro": ("Baterii slabe", "Detaliază bateriile slabe și ce merită înlocuit."),
        "en": ("Low batteries", "Detail the low batteries and what to replace."),
    }),
    (re.compile(r"\biriga", re.I), {
        "id": "fu-topic-irrigation",
        "ro": ("Irigații", "Detaliază irigațiile — ce zone au rulat și când."),
        "en": ("Irrigation", "Detail the irrigation — which zones ran and when."),
    }),
    (re.compile(r"\b(?:solar|produc(?:ție|tie)|pv\b|kwh)", re.I), {
        "id": "fu-topic-solar",
        "ro": ("Producție solară", "Spune-mi mai multe despre producția solară de azi."),
        "en": ("Solar production", "Tell me more about today's solar production."),
    }),
    (re.compile(r"\b(?:poart|garaj|gate)", re.I), {
        "id": "fu-topic-gates",
        "ro": ("Porți", "Verifică starea porților și dacă e ceva de făcut."),
        "en": ("Gates", "Check the gates and whether anything needs doing."),
    }),
    (re.compile(r"\b(?:lumin|aprins)", re.I), {
        "id": "fu-topic-lights",
        "ro": ("Lumini aprinse", "Listează luminile aprinse acum."),
        "en": ("Lights on", "List which lights are on right now."),
    }),
    (re.compile(r"\b(?:climat|termostat|temperatur|aer\s+cond)", re.I), {
        "id": "fu-topic-climate",
        "ro": ("Climă", "Detaliază clima / termostatele acum."),
        "en": ("Climate", "Detail the climate / thermostats right now."),
    }),
    (re.compile(r"\b(?:frigate|camer[aă]|detec)", re.I), {
        "id": "fu-topic-cameras",
        "ro": ("Camere", "Verifică detecțiile recente de pe camere."),
        "en": ("Cameras", "Check recent camera detections."),
    }),
)
_ENTITY_ID_RE = re.compile(r"\b(?:light|switch|cover|scene|binary_sensor|climate|media_player)\.[a-z0-9_]+", re.I)


def enabled(cfg: dict | None = None) -> bool:
    return rl.recs_mode(cfg) != "none"


def _t(lang: str, key: str, **kwargs) -> str:
    table = _I18N.get(lang if lang in _I18N else "en", _I18N["en"])
    text = table.get(key) or _I18N["en"].get(key) or key
    try:
        return text.format(**kwargs)
    except Exception:
        return text


def _chip(id_: str, label: str, prompt: str, kind: str) -> dict:
    return {
        "id": id_[:64],
        "label": label[:80],
        "prompt": prompt[:240],
        "kind": kind if kind in {"action", "ask"} else "ask",
    }


def _day_nonce(extra: str = "") -> str:
    seed = f"{date.today().isoformat()}|{extra}|{int(time.time() // 3600)}"
    return hashlib.sha256(seed.encode()).hexdigest()[:8]


async def _states_map() -> dict[str, dict]:
    try:
        from services import homeassistant as ha

        rows = await ha._fetch_states_cached()  # noqa: SLF001
        return {
            str(s.get("entity_id") or ""): s
            for s in rows
            if isinstance(s, dict) and s.get("entity_id")
        }
    except Exception as e:
        log.debug("states for recommendations unavailable: %s", e)
        return {}


async def _has_energy_stats() -> bool:
    try:
        from services import homeassistant as ha

        result = await ha._ws_call({"type": "recorder/list_statistic_ids"})  # noqa: SLF001
        rows = result if isinstance(result, list) else (
            result.get("statistic_ids") if isinstance(result, dict) else []
        )
        if not isinstance(rows, list):
            return False
        keys = ("solar", "energy", "production", "pv", "grid_export", "energie", "productie")
        for row in rows[:400]:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("statistic_id") or row.get("id") or "").lower()
            if any(k in sid for k in keys):
                return True
        return False
    except Exception:
        return False


def _is_open_like(states: dict[str, dict], entity_id: str, contact_id: str | None = None) -> bool:
    return hw.is_open_like(states, entity_id, contact_id)


def _short_name(name: str) -> str:
    text = re.sub(r"\s+", " ", str(name or "").strip())
    return text[:42]


_OUTDOOR_TEMP_RE = re.compile(
    r"(outdoor|exterior|afara|afar[aă]|weather|meteo|outside)",
    re.I,
)
_INDOOR_HINT_RE = re.compile(
    r"(indoor|interior|room|camera|camer[aă]|living|dormitor|bedroom|bucatar|"
    r"kitchen|baie|bath|hol|hall|casa|home|thermostat|termostat)",
    re.I,
)
_AC_NAME_RE = re.compile(
    r"(ac\b|air.?cond|aer.?cond|climatiz|cool|r[aă]cir|split)",
    re.I,
)
_HEAT_NAME_RE = re.compile(
    r"(heat|caldura|c[aă]ldur[aă]|thermostat|termostat|radiator|boiler|central)",
    re.I,
)
_MANY_LIGHTS_ON = 3
_HOT_C = 25.0
_COOL_C = 22.0
_HEAT_TARGET = 22.0
_COOL_TARGET = 24.0
_EMPTY_LIMIT = 3


def _parse_temp(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _indoor_temperatures(states: dict[str, dict]) -> list[tuple[float, str, str]]:
    """Return [(temp_c, entity_id, name), ...] for indoor-ish temperature sensors."""
    found: list[tuple[float, str, str, int]] = []
    for eid, st in states.items():
        if not eid.startswith(("sensor.", "climate.")):
            continue
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        name = str(attrs.get("friendly_name") or eid)
        blob = f"{name} {eid}"
        if _OUTDOOR_TEMP_RE.search(blob):
            continue
        temp = None
        if eid.startswith("climate."):
            temp = _parse_temp(attrs.get("current_temperature"))
        else:
            dc = str(attrs.get("device_class") or "").lower()
            unit = str(attrs.get("unit_of_measurement") or "").lower()
            if dc not in {"temperature", ""} and "°" not in unit and "c" not in unit:
                if "temp" not in eid.lower() and "temp" not in name.lower():
                    continue
            if dc == "temperature" or "temp" in eid.lower() or "temp" in name.lower() or "°" in unit:
                temp = _parse_temp(st.get("state"))
        if temp is None or temp < -20 or temp > 60:
            continue
        rank = 2 if _INDOOR_HINT_RE.search(blob) else 1
        if eid.startswith("climate."):
            rank += 1
        found.append((temp, eid, name, rank))
    found.sort(key=lambda x: (-x[3], x[0]))
    return [(t, eid, name) for t, eid, name, _ in found]


def _climate_entities(states: dict[str, dict]) -> list[dict]:
    rows = []
    for eid, st in states.items():
        if not eid.startswith("climate."):
            continue
        state = str(st.get("state") or "").lower()
        if state in {"unavailable", "unknown", ""}:
            continue
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        name = str(attrs.get("friendly_name") or eid)
        rows.append({
            "entity_id": eid,
            "name": name,
            "state": state,
            "current": _parse_temp(attrs.get("current_temperature")),
            "target": _parse_temp(attrs.get("temperature")),
            "hvac_modes": attrs.get("hvac_modes") or [],
        })
    return rows


def _pick_climate(rows: list[dict], *, want: str) -> dict | None:
    """want: cool|heat"""
    if not rows:
        return None
    ranked = []
    for row in rows:
        name = f"{row.get('name')} {row.get('entity_id')}"
        score = 1
        modes = [str(m).lower() for m in (row.get("hvac_modes") or [])]
        if want == "cool":
            if _AC_NAME_RE.search(name):
                score += 8
            if any(m in {"cool", "heat_cool"} for m in modes):
                score += 3
            if _HEAT_NAME_RE.search(name) and not _AC_NAME_RE.search(name):
                score -= 4
        else:
            if _HEAT_NAME_RE.search(name):
                score += 8
            if any(m in {"heat", "heat_cool"} for m in modes):
                score += 3
            if _AC_NAME_RE.search(name) and not _HEAT_NAME_RE.search(name):
                score -= 2
        ranked.append((score, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] > 0 else rows[0]


def _lights_currently_on(states: dict[str, dict], habits: dict) -> list[dict]:
    """Actionable lights that are on; prefer habit-named entities over anonymous bulbs."""
    habit_ids = {
        str(r.get("entity_id"))
        for r in (habits.get("lights") or [])
        if isinstance(r, dict) and r.get("entity_id")
    }
    on_rows: list[tuple[int, dict]] = []
    for eid, st in states.items():
        if not eid.startswith("light."):
            continue
        if not hw.is_actionable_entity(eid):
            continue
        if str(st.get("state") or "").lower() != "on":
            continue
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        name = str(attrs.get("friendly_name") or eid)
        if hw.looks_like_bulb_name(name, eid):
            continue
        if hw.is_gateish(name, eid):
            continue
        score = 10 if eid in habit_ids else 1
        # Prefer groups / ambient names.
        if attrs.get("entity_id") and isinstance(attrs.get("entity_id"), (list, tuple)):
            score += 5
        on_rows.append((score, {"entity_id": eid, "name": name}))
    on_rows.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in on_rows]


def climate_candidates(
    states: dict[str, dict],
    *,
    lang: str,
) -> list[tuple[int, dict]]:
    """Scored climate action chips from indoor temp + climate entities."""
    temps = _indoor_temperatures(states)
    if not temps:
        return []
    temp, _src, _ = temps[0]
    climates = _climate_entities(states)
    if not climates:
        return []
    out: list[tuple[int, dict]] = []
    temp_s = f"{temp:.0f}" if abs(temp - round(temp)) < 0.05 else f"{temp:.1f}"

    if temp >= _HOT_C:
        row = _pick_climate(climates, want="cool")
        if not row:
            return []
        name = _short_name(row["name"])
        eid = row["entity_id"]
        state = row["state"]
        target = row.get("target")
        if state in {"off", "idle"} or state not in {"cool", "heat_cool", "auto", "fan_only"}:
            out.append((95, _chip(
                f"ac-on-{eid}",
                _t(lang, "ac_on", name=name),
                _t(lang, "ac_on_prompt", name=name, temp=temp_s),
                "action",
            )))
        elif target is not None and target > _COOL_TARGET:
            out.append((90, _chip(
                f"cool-set-{eid}",
                _t(lang, "cool_lower", name=name, target=int(_COOL_TARGET)),
                _t(lang, "cool_lower_prompt", name=name, temp=temp_s, target=int(_COOL_TARGET)),
                "action",
            )))
    elif temp <= _COOL_C:
        row = _pick_climate(climates, want="heat")
        if not row:
            return []
        name = _short_name(row["name"])
        eid = row["entity_id"]
        state = row["state"]
        target = row.get("target")
        if state in {"off", "idle"}:
            out.append((95, _chip(
                f"heat-on-{eid}",
                _t(lang, "heat_on", name=name),
                _t(lang, "heat_on_prompt", name=name, temp=temp_s),
                "action",
            )))
        elif target is not None and target < _HEAT_TARGET:
            out.append((90, _chip(
                f"heat-set-{eid}",
                _t(lang, "heat_raise", name=name, target=int(_HEAT_TARGET)),
                _t(lang, "heat_raise_prompt", name=name, temp=temp_s, target=int(_HEAT_TARGET)),
                "action",
            )))
    return out


def scored_empty_candidates(
    habits: dict,
    states: dict[str, dict],
    *,
    lang: str,
    period: str,
    hour: int,
    has_energy: bool,
    weather: str = "",
) -> list[tuple[int, dict]]:
    """Ranked (score, chip) for empty chat — higher score = more useful now."""
    scored: list[tuple[int, dict]] = []

    # 1) Climate from live indoor temperature
    scored.extend(climate_candidates(states, lang=lang))

    # 2) Many lights on → suggest turning one off
    on_lights = _lights_currently_on(states, habits)
    if len(on_lights) >= _MANY_LIGHTS_ON:
        row = on_lights[0]
        name = _short_name(row["name"])
        eid = row["entity_id"]
        scored.append((88, _chip(
            f"off-{eid}",
            _t(lang, "turn_off", name=name),
            _t(lang, "turn_off_prompt", name=name),
            "action",
        )))

    # 3) Hour-learned lights that are currently off → turn on
    for row in hw.top_lights_for_period(habits, period=period, hour=hour, limit=6):
        eid = str(row.get("entity_id") or "")
        name = _short_name(row.get("name") or eid)
        if not hw.is_actionable_entity(eid):
            continue
        if hw.looks_like_bulb_name(name, eid) or hw.is_gateish(name, eid):
            continue
        st = states.get(eid) or {}
        if str(st.get("state") or "").lower() == "on":
            continue
        affinity = hw.hour_affinity(row.get("hours"), hour)
        # Need some hour signal, or a strong period count as soft fallback.
        periods = row.get("periods") if isinstance(row.get("periods"), dict) else {}
        period_n = int(periods.get(period) or 0)
        if affinity < 3 and period_n < 2:
            continue
        score = 70 + min(20, affinity * 2) + min(8, period_n)
        scored.append((score, _chip(
            f"on-{eid}",
            _t(lang, "turn_on", name=name),
            _t(lang, "turn_on_prompt", name=name),
            "action",
        )))

    # 4) Gates — prefer morning / afternoon windows; always state-aware
    gate_window = 6 <= hour <= 10 or 15 <= hour <= 19
    for row in hw.top_covers_for_period(habits, period=period, hour=hour, limit=3):
        eid = str(row.get("entity_id") or "")
        name = str(row.get("name") or eid)
        if not hw.is_actionable_entity(eid):
            continue
        if not eid.startswith("cover.") and not hw.is_gateish(name, eid):
            continue
        name = _short_name(name)
        contact = row.get("contact_entity_id")
        is_open = hw.is_open_like(states, eid, contact)
        verb = "close" if is_open else "open"
        affinity = hw.hour_affinity(row.get("hours"), hour)
        score = 55 + min(15, affinity * 2)
        if gate_window:
            score += 20
        # Open gate that's been left open is more urgent than "open it".
        if is_open:
            score += 8
        scored.append((score, _chip(
            f"{verb}-{eid}",
            _t(lang, verb, name=name),
            _t(lang, f"{verb}_prompt", name=name),
            "action",
        )))

    # 5) Asks — house status + solar (daytime) + weather when notable
    scored.append((40, _chip(
        "house-status",
        _t(lang, "house_status"),
        _t(lang, "house_prompt"),
        "ask",
    )))
    if has_energy and 8 <= hour <= 20:
        scored.append((45, _chip(
            "energy-today",
            _t(lang, "energy_today"),
            _t(lang, "energy_prompt"),
            "ask",
        )))
    elif has_energy:
        scored.append((25, _chip(
            "energy-today",
            _t(lang, "energy_today"),
            _t(lang, "energy_prompt"),
            "ask",
        )))
    if weather in {"rainy", "stormy", "snowy", "windy", "pouring"}:
        scored.append((35, _chip(
            "weather",
            _t(lang, "weather"),
            _t(lang, "weather_prompt"),
            "ask",
        )))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def heuristic_empty_actions(
    habits: dict,
    states: dict[str, dict],
    *,
    lang: str,
    period: str,
    limit: int = 4,
    hour: int | None = None,
) -> list[dict]:
    """Backward-compatible helper used by tests — actions only from scored engine."""
    hour = hw.current_hour() if hour is None else hour
    out = []
    for score, chip in scored_empty_candidates(
        habits, states, lang=lang, period=period, hour=hour, has_energy=False
    ):
        if chip.get("kind") != "action":
            continue
        out.append(chip)
        if len(out) >= limit:
            break
    return out


async def build_empty_recs(
    *,
    lang: str = "en",
    atmosphere: dict | None = None,
    habits: dict | None = None,
    limit: int = _EMPTY_LIMIT,
) -> list[dict]:
    """Empty/new chat: max 3 useful chips from live state + hour-learned habits."""
    cfg = load_config()
    if not enabled(cfg):
        return []
    lang = "ro" if str(lang).lower().startswith("ro") else "en"
    if habits is None:
        if hw.needs_refresh(cfg):
            habits = await hw.refresh_habits()
        else:
            habits = hw.load_habits()

    states = await _states_map()
    period = hw.current_period()
    hour = hw.current_hour()
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    weather = str(atmosphere.get("weather") or "").lower()
    has_energy = await _has_energy_stats()
    limit = min(int(limit or _EMPTY_LIMIT), _EMPTY_LIMIT)

    out: list[dict] = []
    seen: set[str] = set()

    def add(chip: dict) -> bool:
        if len(out) >= limit:
            return False
        key = chip["prompt"].strip().lower()
        if key in seen:
            return False
        if rl.is_device_status_chip(chip):
            return False
        seen.add(key)
        out.append(chip)
        return True

    for _score, chip in scored_empty_candidates(
        habits,
        states,
        lang=lang,
        period=period,
        hour=hour,
        has_energy=has_energy,
        weather=weather,
    ):
        add(chip)
        if len(out) >= limit:
            break

    # Soft fill from LLM asks only if we still have slots (never overrides actions).
    mode = rl.recs_mode(cfg)
    if len(out) < limit and mode in {"medium", "high"}:
        llm_items = await rl.ensure_empty_pool(
            lang=lang,
            atmosphere=atmosphere,
            habits=habits,
            states=states,
            wait=False,
        )
        for chip in llm_items:
            if chip.get("kind") == "action":
                continue
            add(chip)
            if len(out) >= limit:
                break

    if not out:
        add(_chip("house-status", _t(lang, "house_status"), _t(lang, "house_prompt"), "ask"))

    return out[:limit]


def _looks_yes_no_question(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or "?" not in raw:
        return False
    # Focus on the last ~2 sentences / last paragraph.
    chunk = raw.split("\n")[-1].strip()
    parts = re.split(r"(?<=[.!?])\s+", chunk)
    last = " ".join(parts[-2:]).strip() if parts else chunk
    return bool(_YESNO_RE.search(last))


def _last_question(text: str) -> str:
    raw = (text or "").strip()
    if not raw or "?" not in raw:
        return ""
    # Prefer the last question mark sentence.
    parts = re.split(r"(?<=\?)\s*", raw)
    for chunk in reversed(parts):
        chunk = chunk.strip()
        if "?" in chunk or chunk.endswith("?"):
            # Take last sentence-ish ending with ?
            m = re.search(r"([^.!?\n]{8,160}\?)\s*$", chunk)
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
            if chunk.endswith("?"):
                return re.sub(r"\s+", " ", chunk[-160:]).strip()
    return ""


def _affirmation_clause(lang: str, question: str) -> str:
    """Turn 'Vrei să verific X?' into a concrete yes clause the model can act on."""
    q = (question or "").strip()
    if not q:
        return "continuă" if lang == "ro" else "continue"
    body = q.rstrip("?").strip()
    # Strip leading offer verbs so the yes-prompt becomes an instruction.
    body = re.sub(
        r"^(?:"
        r"vrei\s+s[aă]\s+|vreți\s+s[aă]\s+|vreti\s+sa\s+|"
        r"poți\s+s[aă]\s+|poti\s+sa\s+|putem\s+s[aă]\s+|"
        r"do\s+you\s+want\s+(?:me\s+)?to\s+|would\s+you\s+like\s+(?:me\s+)?to\s+|"
        r"should\s+i\s+|shall\s+i\s+|can\s+i\s+|can\s+you\s+"
        r")",
        "",
        body,
        flags=re.I,
    ).strip()
    # "verific" (1st person) → "verifică" so the chip reads as a user request.
    if lang == "ro":
        body = re.sub(r"^verific\b", "verifică", body, flags=re.I)
        body = re.sub(r"^uit\b", "uite-te", body, flags=re.I)
        body = re.sub(r"^fac\b", "fă", body, flags=re.I)
    else:
        body = re.sub(r"^check\b", "check", body, flags=re.I)
    body = body[:140].strip(" .,")
    return body or ("continuă" if lang == "ro" else "continue")


def topic_followups_from_reply(assistant_text: str, *, lang: str, limit: int = 3) -> list[dict]:
    """Build topic chips from subjects mentioned in the assistant reply."""
    text = assistant_text or ""
    if len(text) < 40:
        return []
    # Don't scan only the closing question — topics are usually above it.
    body = text
    q = _last_question(text)
    if q and q in body:
        body = body[: body.rfind(q)]
    out: list[dict] = []
    seen: set[str] = set()
    for pattern, meta in _TOPIC_CHIPS:
        if not pattern.search(body):
            continue
        cid = meta["id"]
        if cid in seen:
            continue
        label, prompt = meta.get(lang) or meta["en"]
        seen.add(cid)
        out.append(_chip(cid, label, prompt, "ask"))
        if len(out) >= limit:
            break
    return out


def _yes_no_chips(lang: str, assistant_text: str = "") -> list[dict]:
    """Da/Nu with prompts that keep the prior question — bare 'Da' loses context."""
    question = _last_question(assistant_text)
    clause = _affirmation_clause(lang, question)
    if lang == "ro":
        yes_prompt = f"Da — {clause}."
        no_prompt = "Nu, mulțumesc. Nu e nevoie."
    else:
        yes_prompt = f"Yes — {clause}."
        no_prompt = "No thanks, that's enough."
    return [
        _chip("fu-yes", _t(lang, "yes"), yes_prompt, "ask"),
        _chip("fu-no", _t(lang, "no"), no_prompt, "ask"),
    ]


def followups_for_yes_no_turn(
    *,
    lang: str,
    assistant_text: str,
    limit: int = 3,
) -> list[dict]:
    """Prefer concrete topic chips when the assistant offered more detail."""
    question = _last_question(assistant_text)
    offer = bool(question and _OFFER_DETAIL_RE.search(question))
    topics = topic_followups_from_reply(assistant_text, lang=lang, limit=limit)
    if offer and topics:
        # Lead with a contextual Yes that actually continues the offer, then topics.
        yes_chip = _yes_no_chips(lang, assistant_text)[0]
        merged = [yes_chip]
        for chip in topics:
            if len(merged) >= limit:
                break
            if chip["prompt"].lower() == yes_chip["prompt"].lower():
                continue
            merged.append(chip)
        return merged[:limit]
    if topics and offer:
        return topics[:limit]
    return _yes_no_chips(lang, assistant_text)[:limit]


def classify_turn_intent(
    *,
    user_text: str = "",
    assistant_text: str = "",
    tool_calls: list | None = None,
) -> str:
    """Return HA-ish intents, smalltalk, or chat (non-home topics → few/no chips)."""
    user = (user_text or "").strip()
    if user and _SMALLTALK_RE.match(user):
        return "smalltalk"

    tools = tool_calls or []
    names = {str(t.get("name") or "") for t in tools if isinstance(t, dict)}
    blob = " ".join(
        f"{t.get('name') or ''} {t.get('arguments') or ''}"
        for t in tools
        if isinstance(t, dict)
    ).lower()
    text = f"{user} {assistant_text or ''}".lower()
    ha_tools = any(
        n.startswith("ha_") or n.startswith("frigate") or "search_web" in n
        for n in names
    )
    # Web search alone is not home automation.
    only_web = bool(names) and all(
        ("search" in n or "fetch" in n or n in {"search_web", "fetch_url"})
        for n in names
    )

    if any("statistic" in n or "energy" in n for n in names) or any(
        w in text for w in ("kwh", "energie", "energy", "solar", "consum", "produc")
    ):
        return "energy"
    if "cover" in blob or any(
        w in text for w in ("poart", "gate", "garaj", "garage", "cover", "deschid", "închid", "inchid")
    ):
        return "cover"
    if any(w in blob for w in ("light.", "switch.", "scene.")) or any(
        w in text for w in ("lumin", "light", "aprins", "stins", "bec ", "scene")
    ):
        return "lights"
    if any("frigate" in n or "camera" in n for n in names) or (
        "camera" in text and _HA_TOPIC_RE.search(text)
    ):
        return "cameras"
    if any("weather" in n for n in names) or any(
        w in text for w in ("vremea", "weather", "temperatur")
    ):
        return "weather"
    if ha_tools and not only_web and any(n.startswith("ha_") for n in names):
        return "status"

    # Explicit home topic in the user message.
    if _HA_TOPIC_RE.search(user):
        return "status"

    # Long / philosophical / general chat with no HA tools → chat (not generic HA filler).
    if only_web or (not names and not _HA_TOPIC_RE.search(text)):
        return "chat"

    if not tools and len(user) < 40 and not _HA_TOPIC_RE.search(user):
        return "smalltalk"
    return "chat"


def entities_from_trace(tool_calls: list | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for row in tool_calls or []:
        if not isinstance(row, dict):
            continue
        raw_args = row.get("arguments") or "{}"
        text = raw_args if isinstance(raw_args, str) else json.dumps(raw_args)
        # Also scan result briefly
        text = f"{text} {row.get('result') or ''}"
        for match in _ENTITY_ID_RE.findall(text):
            eid = match.lower()
            if eid not in seen:
                seen.add(eid)
                found.append(eid)
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            args = {}
        if isinstance(args, dict):
            for key in ("entity_id", "entity_ids", "target"):
                val = args.get(key)
                if isinstance(val, str) and "." in val:
                    eid = val.lower()
                    if eid not in seen:
                        seen.add(eid)
                        found.append(eid)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str) and "." in item:
                            eid = item.lower()
                            if eid not in seen:
                                seen.add(eid)
                                found.append(eid)
    return found


def tools_from_trace(tool_calls: list | None) -> list[str]:
    names = []
    for row in tool_calls or []:
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            if name:
                names.append(name)
    return names


async def build_followups(
    *,
    lang: str = "en",
    assistant_text: str = "",
    user_text: str = "",
    tools_used: list[str] | None = None,
    tool_calls: list | None = None,
    habits: dict | None = None,
    limit: int = 3,
) -> list[dict]:
    """ChatGPT-like: only relevant chips; prefer empty over HA spam on chat topics."""
    cfg = load_config()
    if not enabled(cfg):
        return []
    lang = "ro" if str(lang).lower().startswith("ro") else "en"
    habits = habits if isinstance(habits, dict) else hw.load_habits()
    tools = tool_calls
    if tools is None and tools_used:
        tools = [{"name": n} for n in tools_used]
    intent = classify_turn_intent(
        user_text=user_text,
        assistant_text=assistant_text,
        tool_calls=tools,
    )
    mode = rl.recs_mode(cfg)
    if _looks_yes_no_question(assistant_text):
        return followups_for_yes_no_turn(
            lang=lang, assistant_text=assistant_text, limit=limit
        )

    ha_intent = intent in {"lights", "cover", "energy", "cameras", "status", "weather"}
    use_llm = False
    if mode == "high":
        use_llm = True
    elif mode == "medium" and ha_intent:
        use_llm = True
    if use_llm:
        states = {}
        try:
            states = await _states_map()
        except Exception:
            states = {}
        catalog = rl.catalog_lines(habits, states)
        llm_items = await rl.generate_followups(
            lang=lang,
            user_text=user_text,
            assistant_text=assistant_text,
            intent=intent,
            catalog=catalog,
            limit=limit,
        )
        if llm_items:
            return llm_items[:limit]
        if mode == "high" and not ha_intent:
            return []

    return _heuristic_followups(
        lang=lang,
        assistant_text=assistant_text,
        user_text=user_text,
        intent=intent,
        tools=tools,
        habits=habits,
        limit=limit,
    )


def _heuristic_followups(
    *,
    lang: str,
    assistant_text: str,
    user_text: str,
    intent: str,
    tools: list | None,
    habits: dict,
    limit: int,
) -> list[dict]:
    entities = entities_from_trace(tools)
    out: list[dict] = []

    def add(chip: dict) -> None:
        if len(out) >= limit:
            return
        out.append(chip)

    if intent in {"chat", "smalltalk"}:
        return []

    if intent == "weather":
        return []

    if intent == "energy":
        add(_chip("fu-usage", _t(lang, "usage_now"), _t(lang, "usage_prompt"), "ask"))
        return out[:limit]

    if intent == "cover":
        for row in hw.top_covers_for_period(habits, limit=3):
            eid = str(row.get("entity_id") or "")
            if not hw.is_actionable_entity(eid):
                continue
            name = _short_name(row.get("name") or eid)
            if entities and eid not in entities and not any(is_related(eid, e) for e in entities):
                continue
            text_l = f"{user_text} {assistant_text}".lower()
            want_close = any(w in text_l for w in ("deschis", "opened", "open", "aprins"))
            key = "close" if want_close else "open"
            add(_chip(
                f"fu-{key}-{eid}",
                _t(lang, key, name=name),
                _t(lang, f"{key}_prompt", name=name),
                "action",
            ))
            break
        return out[:limit]

    if intent == "lights":
        area_ids = set()
        for eid in entities:
            for row in habits.get("lights") or []:
                if row.get("entity_id") == eid and row.get("area_id"):
                    area_ids.add(row["area_id"])
        companions = []
        for row in hw.top_lights_for_period(habits, limit=6):
            eid = str(row.get("entity_id") or "")
            if eid in entities:
                continue
            if hw.looks_like_bulb_name(str(row.get("name") or ""), eid):
                continue
            if hw.is_gateish(str(row.get("name") or ""), eid):
                continue
            if area_ids and row.get("area_id") not in area_ids:
                continue
            companions.append(row)
        if companions:
            row = companions[0]
            name = _short_name(row.get("name") or row.get("entity_id"))
            add(_chip(
                f"fu-also-{row.get('entity_id')}",
                _t(lang, "also_same_area", name=name),
                _t(lang, "also_same_area_prompt", name=name),
                "action",
            ))
        if entities:
            eid = entities[0]
            if not hw.is_gateish("", eid) and (eid.startswith("light.") or eid.startswith("switch.")):
                name = eid
                for row in habits.get("lights") or []:
                    if row.get("entity_id") == eid:
                        name = row.get("name") or eid
                        break
                name = _short_name(name)
                add(_chip(
                    f"fu-off-{eid}",
                    _t(lang, "turn_off", name=name),
                    _t(lang, "turn_off_prompt", name=name),
                    "action",
                ))
        return out[:limit]

    if intent in {"cameras", "status"}:
        topics = topic_followups_from_reply(assistant_text, lang=lang, limit=limit)
        for chip in topics:
            add(chip)
        if not out:
            add(_chip("fu-house", _t(lang, "house_status"), _t(lang, "house_prompt"), "ask"))
        return out[:limit]
    return []


def is_related(a: str, b: str) -> bool:
    a = (a or "").lower()
    b = (b or "").lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return a.split(".", 1)[-1][:6] == b.split(".", 1)[-1][:6]