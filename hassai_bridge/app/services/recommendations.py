"""Build empty-chat and follow-up recommendation chips (no LLM)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date

from core.config import load_config
from services import habit_watcher as hw

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
        "house_prompt": "Give me a short home status — lights on, doors/gates, climate.",
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
        "house_prompt": "Dă-mi pe scurt statusul casei — lumini aprinse, uși/porți, climă.",
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
_ENTITY_ID_RE = re.compile(r"\b(?:light|switch|cover|scene|binary_sensor|climate|media_player)\.[a-z0-9_]+", re.I)


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


def _is_open_like(states: dict[str, dict], entity_id: str, contact_id: str | None = None) -> bool:
    """True if gate/cover looks open (prefer contact sensor when present)."""
    if contact_id:
        cst = states.get(contact_id) or {}
        cstate = str(cst.get("state") or "").lower()
        # HA door contact: on usually means open/detected
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


def _short_name(name: str) -> str:
    text = re.sub(r"\s+", " ", str(name or "").strip())
    return text[:42]


def _scene_for_area(habits: dict, area_id: str | None, area_name: str, period: str) -> dict | None:
    if period not in {"evening", "night"}:
        return None
    area_l = (area_name or "").lower()
    for scene in habits.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        s_area = str(scene.get("area_id") or "")
        s_name = str(scene.get("name") or "")
        if area_id and s_area and s_area == area_id:
            return scene
        if area_l and area_l in s_name.lower():
            return scene
        if "seara" in s_name.lower() or "evening" in s_name.lower():
            if not area_l or area_l.split()[0] in s_name.lower():
                return scene
    return None


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
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    weather = str(atmosphere.get("weather") or "").lower()
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

    # 1) Cover / gate actions with correct open/close verb
    for row in hw.top_covers_for_period(habits, period=period, limit=2):
        eid = str(row.get("entity_id") or "")
        name = _short_name(row.get("name") or eid)
        contact = row.get("contact_entity_id")
        is_open = _is_open_like(states, eid, contact)
        if is_open:
            add(_chip(
                f"close-{eid}",
                _t(lang, "close", name=name),
                _t(lang, "close_prompt", name=name),
                "action",
            ))
        else:
            add(_chip(
                f"open-{eid}",
                _t(lang, "open", name=name),
                _t(lang, "open_prompt", name=name),
                "action",
            ))

    # 2) Preferred light groups (bulbs already rolled up / filtered)
    light_actions = 0
    for row in hw.top_lights_for_period(habits, period=period, limit=5):
        if light_actions >= 2:
            break
        eid = str(row.get("entity_id") or "")
        name = _short_name(row.get("name") or eid)
        if hw.looks_like_bulb_name(name, eid) or hw.is_gateish(name, eid):
            continue
        st = states.get(eid) or {}
        state = str(st.get("state") or "").lower()
        # Prefer evening scene over raw light when available
        scene = _scene_for_area(
            habits,
            row.get("area_id"),
            str(row.get("area_name") or ""),
            period,
        )
        if scene and state != "on" and period in {"evening", "night"}:
            sname = _short_name(scene.get("name") or scene.get("entity_id"))
            add(_chip(
                f"scene-{scene.get('entity_id')}",
                _t(lang, "activate_scene", name=sname),
                _t(lang, "activate_scene_prompt", name=sname),
                "action",
            ))
            light_actions += 1
            continue
        if state == "on":
            continue
        add(_chip(
            f"on-{eid}",
            _t(lang, "turn_on", name=name),
            _t(lang, "turn_on_prompt", name=name),
            "action",
        ))
        light_actions += 1

    # 3) Contextual asks
    if weather in {"rainy", "stormy", "snowy", "windy"} or weather:
        add(_chip("weather", _t(lang, "weather"), _t(lang, "weather_prompt"), "ask"))

    if await _has_energy_stats():
        add(_chip("energy-today", _t(lang, "energy_today"), _t(lang, "energy_prompt"), "ask"))

    add(_chip("house-status", _t(lang, "house_status"), _t(lang, "house_prompt"), "ask"))

    fr = cfg.get("frigate") if isinstance(cfg.get("frigate"), dict) else {}
    if fr.get("enabled") is not False:
        add(_chip("cameras", _t(lang, "cameras"), _t(lang, "cameras_prompt"), "ask"))

    if light_actions == 0:
        add(_chip("list-lights", _t(lang, "list_lights"), _t(lang, "list_lights_prompt"), "ask"))

    nonce = _day_nonce(period + weather)
    actions = [c for c in out if c["kind"] == "action"]
    asks = [c for c in out if c["kind"] != "action"]
    asks.sort(key=lambda c: hashlib.md5(f"{nonce}:{c['id']}".encode()).hexdigest())
    return (actions[:2] + asks)[:limit]


def _looks_yes_no_question(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or "?" not in raw:
        return False
    # Focus on the last ~2 sentences / last paragraph.
    chunk = raw.split("\n")[-1].strip()
    parts = re.split(r"(?<=[.!?])\s+", chunk)
    last = " ".join(parts[-2:]).strip() if parts else chunk
    return bool(_YESNO_RE.search(last))


def _yes_no_chips(lang: str) -> list[dict]:
    return [
        _chip("fu-yes", _t(lang, "yes"), _t(lang, "yes_prompt"), "ask"),
        _chip("fu-no", _t(lang, "no"), _t(lang, "no_prompt"), "ask"),
    ]


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


def build_followups(
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
    entities = entities_from_trace(tools)
    out: list[dict] = []

    def add(chip: dict) -> None:
        if len(out) >= limit:
            return
        out.append(chip)

    # Non-home conversation: Da/Nu if the assistant asked a yes/no question, else nothing.
    if intent in {"chat", "smalltalk"}:
        if _looks_yes_no_question(assistant_text):
            return _yes_no_chips(lang)[:limit]
        return []

    if intent == "weather":
        if _looks_yes_no_question(assistant_text):
            return _yes_no_chips(lang)[:limit]
        return []

    if intent == "energy":
        add(_chip("fu-usage", _t(lang, "usage_now"), _t(lang, "usage_prompt"), "ask"))
        return out[:limit]

    if intent == "cover":
        for row in hw.top_covers_for_period(habits, limit=3):
            eid = str(row.get("entity_id") or "")
            name = _short_name(row.get("name") or eid)
            if entities and eid not in entities and not any(is_related(eid, e) for e in entities):
                continue
            # Suggest close after open-ish talk, else open.
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
        if _looks_yes_no_question(assistant_text):
            for chip in _yes_no_chips(lang):
                add(chip)
        return out[:limit]

    if intent in {"cameras", "status"}:
        if _looks_yes_no_question(assistant_text):
            return _yes_no_chips(lang)[:limit]
        # Only house status when the turn was actually about the home.
        add(_chip("fu-house", _t(lang, "house_status"), _t(lang, "house_prompt"), "ask"))
        return out[:limit]

    # Fallback: never inject Status casă into unrelated chats.
    if _looks_yes_no_question(assistant_text):
        return _yes_no_chips(lang)[:limit]
    return []


def is_related(a: str, b: str) -> bool:
    a = (a or "").lower()
    b = (b or "").lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return a.split(".", 1)[-1][:6] == b.split(".", 1)[-1][:6]