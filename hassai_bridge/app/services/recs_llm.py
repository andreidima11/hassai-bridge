"""LLM-backed recommendation chips — pool (empty chat) + optional follow-ups.

Token budget by mode:
- none: no calls
- medium: refresh empty pool on period/weather change or ~4h; follow-ups only on HA turns
- high: refresh empty pool ~15 min; follow-ups on almost every assistant turn
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from core.config import DATA_DIR, load_config, save_config
from services import habit_watcher as hw

log = logging.getLogger("hassai.recs_llm")

POOL_FILE = DATA_DIR / "recs_pool.json"
_JSON_ARR = re.compile(r"\[[\s\S]*\]")
_gen_lock = asyncio.Lock()
_followup_cache: dict[str, tuple[float, list[dict]]] = {}
_FOLLOWUP_TTL = 90.0


def recs_mode(cfg: dict | None = None) -> str:
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    rec = cfg.get("recommendations") if isinstance(cfg.get("recommendations"), dict) else {}
    if not isinstance(rec, dict):
        rec = {}
    if rec.get("enabled") is False:
        return "none"
    mode = str(rec.get("mode") or "medium").strip().lower()
    if mode in {"none", "off", "disabled"}:
        return "none"
    if mode in {"high", "max", "full"}:
        return "high"
    return "medium"


def normalize_recs_cfg(raw) -> dict:
    src = dict(raw) if isinstance(raw, dict) else {}
    enabled = src.get("enabled")
    mode = str(src.get("mode") or "").strip().lower()
    if not mode:
        mode = "none" if enabled is False else "medium"
    if mode in {"off", "disabled"}:
        mode = "none"
    if mode not in {"none", "medium", "high"}:
        mode = "medium"
    return {
        "enabled": mode != "none",
        "mode": mode,
        "learn_from_chat": src.get("learn_from_chat") is not False,
        "provider_id": str(src.get("provider_id") or "").strip()[:120],
        "model": str(src.get("model") or "").strip()[:200],
        "last_generated_at": float(src.get("last_generated_at") or 0) or 0.0,
        "status": str(src.get("status") or "idle")[:40],
        "error": str(src.get("error") or "")[:300],
    }


def _block(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return normalize_recs_cfg(cfg.get("recommendations"))


def _save_block(block: dict) -> None:
    cfg = load_config()
    cfg["recommendations"] = normalize_recs_cfg(block)
    save_config(cfg)


def resolve_recs_provider(cfg: dict | None = None) -> dict:
    from services import providers as pv

    cfg = cfg or load_config()
    pid = _block(cfg).get("provider_id") or ""
    if pid:
        found = pv.get_provider_by_id(pid)
        if found:
            return found
    return pv.get_active_provider()


def resolve_recs_model(provider: dict | None = None, cfg: dict | None = None) -> str | None:
    block = _block(cfg)
    explicit = str(block.get("model") or "").strip()
    if explicit:
        return explicit
    provider = provider or {}
    roles = provider.get("role_models") if isinstance(provider.get("role_models"), dict) else {}
    fast = str((roles or {}).get("fast") or "").strip()
    if fast:
        return fast
    default = str(provider.get("model") or "").strip()
    return default or None


def _parse_chip_array(text: str) -> list[dict]:
    raw = (text or "").strip()
    if "```" in raw:
        raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_ARR.search(raw)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        prompt = str(row.get("prompt") or label).strip()
        if not label or not prompt:
            continue
        kind = str(row.get("kind") or "ask")
        if kind not in {"action", "ask"}:
            kind = "ask"
        out.append({
            "id": str(row.get("id") or label)[:64],
            "label": label[:80],
            "prompt": prompt[:240],
            "kind": kind,
        })
        if len(out) >= 5:
            break
    return out


def load_pool() -> dict:
    try:
        data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.debug("recs pool load failed: %s", e)
        return {}


def save_pool(items: list[dict], *, period: str, weather: str, lang: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "items": items,
        "generated_at": time.time(),
        "period": period,
        "weather": weather,
        "lang": lang,
    }
    tmp = POOL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(POOL_FILE)


def pool_stale(cfg: dict | None, *, period: str, weather: str, lang: str) -> bool:
    mode = recs_mode(cfg)
    if mode == "none":
        return False
    pool = load_pool()
    items = pool.get("items") if isinstance(pool.get("items"), list) else []
    if len(items) < 2:
        return True
    if str(pool.get("period") or "") != period:
        return True
    if str(pool.get("lang") or "") != lang:
        return True
    if weather and str(pool.get("weather") or "") != weather:
        return True
    age = time.time() - float(pool.get("generated_at") or 0)
    if mode == "high":
        return age >= 15 * 60
    return age >= 4 * 3600


_DEVICE_STATUS_RE = re.compile(
    r"(starea|stare(?:a)?|status)\s+(por[tțţ]|poar[tțţ]|gate|usa|uș[aă]|cover|garaj|garage)|"
    r"(starea|stare(?:a)?|status).{0,24}(por[tțţ]i[ei]?|poar[tțţ](?:ei|ii)?|gate|garaj|garage)|"
    r"(por[tțţ]|poar[tțţ]|gate|garaj|garage).{0,24}(stare|status|deschis\?|închis\?|inchis\?|open\?|closed\?)|"
    r"(e\s+deschis[aă]?|e\s+închis[aă]?|e\s+inchis[aă]?|is\s+(?:the\s+)?(?:gate|door)\s+open|"
    r"open\s+or\s+closed).{0,24}(por[tțţ]|poar[tțţ]|gate|usa|uș[aă]|garaj|garage)",
    re.I,
)


def is_device_status_chip(chip: dict | None) -> bool:
    """True for 'what's the gate state' chips — never useful as a suggestion."""
    if not isinstance(chip, dict):
        return False
    cid = str(chip.get("id") or "").lower()
    if cid in {"house-status", "energy-today", "weather", "cameras", "list-lights"}:
        return False
    blob = f"{chip.get('label') or ''} {chip.get('prompt') or ''}"
    low = blob.lower()
    if "input_boolean" in low:
        return True
    # Whole-home status is fine; per-device gate/door status is not.
    if re.search(r"\b(status\s+cas|home\s+status|statusul\s+casei)\b", low):
        return False
    return bool(_DEVICE_STATUS_RE.search(blob))


def catalog_lines(
    habits: dict,
    states: dict[str, dict],
    *,
    limit: int = 36,
) -> list[str]:
    rows: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(eid: str, name: str, kind: str, extra: str = "", score: int = 1) -> None:
        eid = str(eid or "")
        if not eid or eid in seen or not hw.is_actionable_entity(eid):
            return
        seen.add(eid)
        st = states.get(eid) or {}
        state = str(st.get("state") or "?")[:16]
        label = str(name or eid)[:42]
        rows.append((score, f"{eid} | {label} | {kind} | {state}{extra}"))

    for row in hw.top_covers_for_period(habits, limit=4):
        eid = str(row.get("entity_id") or "")
        contact = str(row.get("contact_entity_id") or "")
        extra = f" | contact={contact}" if contact else ""
        need = "close" if hw.is_open_like(states, eid, contact or None) else "open"
        extra = f"{extra} | need={need}"
        add(eid, row.get("name"), "gate/cover", extra, 50)
    for row in hw.top_lights_for_period(habits, limit=10):
        eid = str(row.get("entity_id") or "")
        st = states.get(eid) or {}
        on = str(st.get("state") or "").lower() == "on"
        extra = " | need=skip" if on else " | need=turn_on"
        add(eid, row.get("name"), row.get("kind") or "light", extra, 40)
    for scene in (habits.get("scenes") or [])[:8]:
        if isinstance(scene, dict):
            add(scene.get("entity_id"), scene.get("name"), "scene", " | need=activate", 20)
    rows.sort(key=lambda x: x[0], reverse=True)
    return [line for _, line in rows[:limit]]


def _message_content(result: dict) -> str:
    try:
        content = result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return str(content)


async def _complete(messages: list[dict], *, max_tokens: int, timeout: float) -> str:
    from services import providers as pv

    cfg = load_config()
    provider = resolve_recs_provider(cfg)
    model = resolve_recs_model(provider, cfg)
    coro = pv.chat_completion(
        messages,
        model=model,
        stream=False,
        provider=provider,
        thinking={"enabled": False},
        max_tokens=max_tokens,
    )
    result = await asyncio.wait_for(coro, timeout=timeout)
    return _message_content(result)


async def generate_empty_pool(
    *,
    lang: str,
    atmosphere: dict | None,
    habits: dict,
    states: dict[str, dict],
) -> list[dict]:
    mode = recs_mode()
    if mode == "none":
        return []
    period = hw.current_period()
    weather = str((atmosphere or {}).get("weather") or "")
    catalog = catalog_lines(habits, states)
    if not catalog:
        return []
    lang_name = "Romanian" if lang == "ro" else "English"
    prompt = (
        f"You pick extra ASK chips for an empty Home Assistant chat (HASSAI).\n"
        f"Language for labels AND prompts: {lang_name}.\n"
        f"Time of day: {period}. Weather: {weather or 'unknown'}.\n\n"
        f"Catalog (entity_id | name | kind | state | need=...):\n"
        + "\n".join(catalog)
        + "\n\nReturn ONLY a JSON array of 2 or 3 objects: "
        '{"id":"...","label":"...","prompt":"...","kind":"ask"}.\n'
        "Rules:\n"
        "- ONLY kind=ask. Do not emit device actions (open/close/turn on) — those are built live.\n"
        "- NEVER suggest checking a device's state (no 'Starea porții', no 'is the gate open').\n"
        "- Asks: weather, energy, cameras, or a short house summary — not per-device status.\n"
        "- Never recommend input_boolean, binary_sensor, or raw entity_id as the label.\n"
        "- Labels max ~6 words, human names only."
    )
    timeout = 12.0 if mode == "high" else 8.0
    try:
        raw = await _complete(
            [
                {"role": "system", "content": "Output JSON only. No markdown."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=700,
            timeout=timeout,
        )
        items = _parse_chip_array(raw)
        items = _filter_against_catalog(items, catalog)
        items = [c for c in items if not is_device_status_chip(c)]
        if len(items) >= 1:
            save_pool(items, period=period, weather=weather, lang=lang)
            block = _block()
            block["last_generated_at"] = time.time()
            block["status"] = "ok"
            block["error"] = ""
            _save_block(block)
            return items
    except Exception as e:
        log.warning("recs empty pool LLM failed: %s", e)
        block = _block()
        block["status"] = "error"
        block["error"] = str(e)[:300]
        _save_block(block)
    return []


def _filter_against_catalog(items: list[dict], catalog: list[str]) -> list[dict]:
    out = []
    for chip in items:
        if is_device_status_chip(chip):
            continue
        prompt = str(chip.get("prompt") or "").lower()
        label = str(chip.get("label") or "").lower()
        if "input_boolean" in prompt or "input_boolean" in label:
            continue
        kind = chip.get("kind")
        if kind != "action":
            out.append(chip)
            continue
        ok = False
        for line in catalog:
            parts = [p.strip().lower() for p in line.split("|")]
            eid = parts[0] if parts else ""
            name = parts[1] if len(parts) > 1 else ""
            if eid and eid in prompt:
                ok = True
                break
            if name and len(name) > 3 and (name in label or name in prompt):
                ok = True
                break
        if ok:
            out.append(chip)
    return out[:5]


async def ensure_empty_pool(
    *,
    lang: str,
    atmosphere: dict | None,
    habits: dict,
    states: dict[str, dict],
    wait: bool = False,
) -> list[dict]:
    mode = recs_mode()
    if mode == "none":
        return []
    period = hw.current_period()
    weather = str((atmosphere or {}).get("weather") or "")
    pool = load_pool()
    cached = pool.get("items") if isinstance(pool.get("items"), list) else []
    stale = pool_stale(None, period=period, weather=weather, lang=lang)
    if not stale and cached:
        return cached
    if wait or (mode == "high" and not cached):
        async with _gen_lock:
            return await generate_empty_pool(
                lang=lang, atmosphere=atmosphere, habits=habits, states=states
            ) or cached
    # medium / high with stale cache: refresh in background, serve cache
    if not _gen_lock.locked():
        asyncio.create_task(_bg_refresh(lang, atmosphere, habits, states))
    return cached


async def _bg_refresh(lang, atmosphere, habits, states):
    try:
        async with _gen_lock:
            await generate_empty_pool(
                lang=lang, atmosphere=atmosphere, habits=habits, states=states
            )
    except Exception as e:
        log.debug("bg recs pool: %s", e)


async def generate_followups(
    *,
    lang: str,
    user_text: str,
    assistant_text: str,
    intent: str,
    catalog: list[str],
    limit: int = 3,
) -> list[dict]:
    mode = recs_mode()
    if mode == "none":
        return []
    key = f"{lang}|{intent}|{user_text[:180]}|{assistant_text[:220]}"
    hit = _followup_cache.get(key)
    if hit and time.time() - hit[0] < _FOLLOWUP_TTL:
        return hit[1]
    lang_name = "Romanian" if lang == "ro" else "English"
    ha = intent in {"lights", "cover", "energy", "cameras", "status", "weather"}
    catalog_block = "\n".join(catalog[:16]) if ha and catalog else "(no home entities needed)"
    prompt = (
        f"Suggest up to {limit} follow-up chips after this chat turn. Language: {lang_name}.\n"
        f"User: {user_text[:500]}\n"
        f"Assistant: {assistant_text[:900]}\n"
        f"Intent: {intent}\n"
        f"Home catalog:\n{catalog_block}\n\n"
        "Return ONLY a JSON array of {id,label,prompt,kind}.\n"
        "If the assistant asked a yes/no confirmation, Da/Nu (or Yes/No) chips are OK — "
        "but the prompt MUST restate what they agree to (never bare 'Da'/'Yes').\n"
        "If the assistant offered more detail on topics already mentioned (irrigation, "
        "batteries, flood sensors, etc.), prefer 2–3 topic chips over bare yes/no.\n"
        "If this is NOT about the smart home, continue the TOPIC (never Status casă / home status).\n"
        "Never suggest checking a gate/door/cover state — suggest Open/Close from catalog `need=` instead.\n"
        "If nothing useful, return [].\n"
        "Home actions: only catalog entities; gates Open/Close not Turn on; no input_boolean."
    )
    timeout = 8.0 if mode == "high" else 3.5
    try:
        raw = await _complete(
            [
                {"role": "system", "content": "Output JSON only. Empty array is allowed."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            timeout=timeout,
        )
        items = _parse_chip_array(raw)[:limit]
        items = [
            c for c in items
            if not is_device_status_chip(c)
            and "input_boolean" not in str(c.get("prompt") or "").lower()
            and "input_boolean" not in str(c.get("label") or "").lower()
        ]
        _followup_cache[key] = (time.time(), items)
        if len(_followup_cache) > 80:
            oldest = sorted(_followup_cache.items(), key=lambda kv: kv[1][0])[:40]
            for k, _ in oldest:
                _followup_cache.pop(k, None)
        return items
    except Exception as e:
        log.debug("recs followup LLM failed: %s", e)
        return []
