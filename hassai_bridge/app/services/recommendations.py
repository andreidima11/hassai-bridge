"""Build empty-chat and follow-up recommendation chips (no LLM)."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date

from core.config import load_config
from services import habit_watcher as hw

log = logging.getLogger("hassai.recommendations")

_I18N = {
    "en": {
        "turn_on": "Turn on {name}",
        "turn_on_prompt": "Turn on {name}",
        "energy_today": "How much energy did I produce today?",
        "energy_prompt": "How much solar/energy did I produce today? Summarize from Home Assistant statistics if available.",
        "house_status": "What's the house status?",
        "house_prompt": "Give me a short status of the home — lights on, doors, climate.",
        "cameras": "What's on the cameras?",
        "cameras_prompt": "Check recent Frigate detections and tell me briefly what's going on.",
        "detail": "Tell me more",
        "detail_prompt": "Go into a bit more detail on that.",
        "also_hall": "Turn on the hallway too",
        "also_hall_prompt": "Also turn on the hallway light if it exists.",
        "usage_now": "What's using power now?",
        "usage_prompt": "What devices or sensors show high power usage right now?",
        "list_lights": "Which lights are on?",
        "list_lights_prompt": "List which lights are currently on.",
    },
    "ro": {
        "turn_on": "Aprinde {name}",
        "turn_on_prompt": "Aprinde {name}",
        "energy_today": "Cât curent am produs azi?",
        "energy_prompt": "Cât curent / energie solară am produs azi? Rezumat din statisticile Home Assistant dacă există.",
        "house_status": "Cum stă casa?",
        "house_prompt": "Dă-mi pe scurt starea casei — lumini aprinse, uși, climă.",
        "cameras": "Ce e pe camere?",
        "cameras_prompt": "Verifică detecțiile recente Frigate și spune pe scurt ce se întâmplă.",
        "detail": "Mai multe detalii",
        "detail_prompt": "Detaliază puțin mai mult.",
        "also_hall": "Aprinde și holul",
        "also_hall_prompt": "Aprinde și lumina de pe hol, dacă există.",
        "usage_now": "Ce consumă acum?",
        "usage_prompt": "Ce dispozitive sau senzori arată consum mare acum?",
        "list_lights": "Ce lumini sunt aprinse?",
        "list_lights_prompt": "Listează luminile care sunt aprinse acum.",
    },
}


def enabled(cfg: dict | None = None) -> bool:
    return hw.enabled(cfg)


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


async def build_empty_recs(
    *,
    lang: str = "en",
    atmosphere: dict | None = None,
    habits: dict | None = None,
    limit: int = 5,
) -> list[dict]:
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
    out: list[dict] = []
    seen: set[str] = set()

    def add(chip: dict) -> None:
        if len(out) >= limit:
            return
        key = chip["prompt"].strip().lower()
        if key in seen:
            return
        seen.add(key)
        out.append(chip)

    for row in hw.top_lights_for_period(habits, period=period, limit=4):
        eid = row.get("entity_id") or ""
        name = row.get("name") or eid
        st = states.get(eid) or {}
        if str(st.get("state") or "").lower() == "on":
            continue
        add(_chip(
            f"on-{eid}",
            _t(lang, "turn_on", name=name),
            _t(lang, "turn_on_prompt", name=name),
            "action",
        ))
        if len(out) >= 2:
            break

    if await _has_energy_stats():
        add(_chip("energy-today", _t(lang, "energy_today"), _t(lang, "energy_prompt"), "ask"))

    add(_chip("house-status", _t(lang, "house_status"), _t(lang, "house_prompt"), "ask"))

    fr = cfg.get("frigate") if isinstance(cfg.get("frigate"), dict) else {}
    if fr.get("enabled") is not False:
        add(_chip("cameras", _t(lang, "cameras"), _t(lang, "cameras_prompt"), "ask"))

    add(_chip("list-lights", _t(lang, "list_lights"), _t(lang, "list_lights_prompt"), "ask"))

    nonce = _day_nonce(period)
    out.sort(key=lambda c: hashlib.md5(f"{nonce}:{c['id']}".encode()).hexdigest())
    actions = [c for c in out if c["kind"] == "action"]
    asks = [c for c in out if c["kind"] != "action"]
    return (actions[:2] + asks)[:limit]


def build_followups(
    *,
    lang: str = "en",
    assistant_text: str = "",
    tools_used: list[str] | None = None,
    limit: int = 3,
) -> list[dict]:
    cfg = load_config()
    if not enabled(cfg):
        return []
    lang = "ro" if str(lang).lower().startswith("ro") else "en"
    tools = {str(t or "") for t in (tools_used or [])}
    text = (assistant_text or "").lower()
    out: list[dict] = []

    def add(chip: dict) -> None:
        if len(out) >= limit:
            return
        out.append(chip)

    add(_chip("fu-detail", _t(lang, "detail"), _t(lang, "detail_prompt"), "ask"))

    if any(t.startswith("ha_") or "light" in t or "switch" in t for t in tools) or any(
        w in text for w in ("lumin", "light", "aprins", "turned on", "am aprins")
    ):
        add(_chip("fu-hall", _t(lang, "also_hall"), _t(lang, "also_hall_prompt"), "action"))

    if any("statistic" in t or "energy" in t for t in tools) or any(
        w in text for w in ("kwh", "energie", "energy", "solar", "consum")
    ):
        add(_chip("fu-usage", _t(lang, "usage_now"), _t(lang, "usage_prompt"), "ask"))
    else:
        add(_chip("fu-house", _t(lang, "house_status"), _t(lang, "house_prompt"), "ask"))

    return out[:limit]


def tools_from_trace(tool_calls: list | None) -> list[str]:
    names = []
    for row in tool_calls or []:
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            if name:
                names.append(name)
    return names
