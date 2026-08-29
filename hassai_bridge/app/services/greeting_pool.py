"""LLM-refreshed chat greeting pool (seasonal + weather/holiday tags).

Built-in curated greetings stay as fallback on the client. The server keeps a
generated overlay refreshed every N days (and when the season/holiday window
changes), so December gets Christmas-ready lines without waiting for a manual
edit.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import DATA_DIR, load_config, save_config

log = logging.getLogger("hassai.greetings")

POOL_FILE = DATA_DIR / "greeting_pool.json"
ALLOWED_TAGS = frozenset({
    "general", "morning", "afternoon", "evening", "night",
    "rainy", "snowy", "sunny", "clear_night", "stormy", "foggy", "cloudy", "windy", "hot", "cold",
    "easter", "christmas", "new_year", "new_year_eve", "valentine", "halloween",
    "national_day", "labor_day", "martisor", "womens_day", "pentecost",
    "assumption", "st_andrew", "union_day",
})
_DEFAULTS = {
    "refresh_days": 7,
    "pool_size": 40,
    "provider_id": "",
    "model": "",
    "last_generated_at": 0.0,
    "last_season_key": "",
    "status": "idle",
    "error": "",
}
_gen_lock = False


def normalize_greetings_cfg(raw: Any) -> dict:
    src = dict(raw) if isinstance(raw, dict) else {}
    try:
        days = int(src.get("refresh_days", _DEFAULTS["refresh_days"]))
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))
    try:
        size = int(src.get("pool_size", _DEFAULTS["pool_size"]))
    except (TypeError, ValueError):
        size = 40
    size = max(12, min(size, 80))
    try:
        last = float(src.get("last_generated_at") or 0)
    except (TypeError, ValueError):
        last = 0.0
    return {
        "refresh_days": days,
        "pool_size": size,
        "provider_id": str(src.get("provider_id") or "").strip()[:120],
        "model": str(src.get("model") or "").strip()[:200],
        "last_generated_at": last,
        "last_season_key": str(src.get("last_season_key") or ""),
        "status": str(src.get("status") or "idle"),
        "error": str(src.get("error") or "")[:300],
    }


def resolve_greeting_provider(cfg: dict | None = None) -> dict:
    """Provider used for pool generation. Empty provider_id → active chat provider."""
    from services import providers as pv

    cfg = cfg or load_config()
    block = _cfg_block(cfg)
    pid = block.get("provider_id") or ""
    if pid:
        found = pv.get_provider_by_id(pid)
        if found:
            return found
    return pv.get_active_provider()


def resolve_greeting_model(provider: dict | None, block: dict | None = None) -> str | None:
    """Explicit model, else provider fast role model, else provider default (None)."""
    block = block or _cfg_block()
    explicit = str((block or {}).get("model") or "").strip()
    if explicit:
        return explicit
    provider = provider or {}
    roles = provider.get("role_models") if isinstance(provider.get("role_models"), dict) else {}
    fast = str((roles or {}).get("fast") or "").strip()
    if fast:
        return fast
    default = str(provider.get("model") or "").strip()
    return default or None


def _cfg_block(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return normalize_greetings_cfg(cfg.get("greetings"))


def _save_cfg_block(block: dict) -> None:
    cfg = load_config()
    cfg["greetings"] = normalize_greetings_cfg(block)
    save_config(cfg)


def load_pool() -> dict:
    if not POOL_FILE.is_file():
        return {"version": 1, "items": [], "generated_at": 0, "season_key": ""}
    try:
        data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "items": [], "generated_at": 0, "season_key": ""}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        return {
            "version": 1,
            "items": [x for x in items if isinstance(x, dict)],
            "generated_at": float(data.get("generated_at") or 0),
            "season_key": str(data.get("season_key") or ""),
        }
    except Exception as exc:
        log.warning("greeting pool read failed: %s", exc)
        return {"version": 1, "items": [], "generated_at": 0, "season_key": ""}


def save_pool(items: list[dict], *, season_key: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": time.time(),
        "season_key": season_key,
        "items": items,
    }
    tmp = POOL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(POOL_FILE)


# ── Calendar / season ────────────────────────────────────────────────────────

def _orthodox_easter(year: int) -> date:
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    return date(year, month, day) + timedelta(days=13)


def _western_easter(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def upcoming_holidays(lang: str, today: date | None = None, horizon_days: int = 45) -> list[dict]:
    """Holidays in [today-2, today+horizon] for prompt + season key."""
    today = today or date.today()
    y = today.year
    end = today + timedelta(days=horizon_days)
    start = today - timedelta(days=2)
    events: list[tuple[date, str, str]] = []

    def add(d: date, hid: str, label: str) -> None:
        if start <= d <= end:
            events.append((d, hid, label))

    if lang == "ro":
        oe = _orthodox_easter(y)
        add(oe, "easter", "Paște ortodox")
        add(oe + timedelta(days=1), "easter", "A doua zi de Paște")
        add(oe + timedelta(days=49), "pentecost", "Rusalii")
        if y + 1 <= end.year:
            oe2 = _orthodox_easter(y + 1)
            add(oe2, "easter", "Paște ortodox")
        add(date(y, 3, 1), "martisor", "Mărțișor")
        add(date(y, 3, 8), "womens_day", "Ziua Femeii")
        add(date(y, 5, 1), "labor_day", "1 Mai")
        add(date(y, 8, 15), "assumption", "Adormirea Maicii Domnului")
        add(date(y, 11, 30), "st_andrew", "Sfântul Andrei")
        add(date(y, 12, 1), "national_day", "Ziua Națională")
        add(date(y, 1, 24), "union_day", "Unirea Principatelor")
    else:
        we = _western_easter(y)
        add(we, "easter", "Easter")
        add(we + timedelta(days=1), "easter", "Easter Monday")
        add(date(y, 10, 31), "halloween", "Halloween")
        add(date(y, 5, 1), "labor_day", "Labor Day")

    add(date(y, 2, 14), "valentine", "Valentine's Day / Dragobete vibe")
    add(date(y, 12, 25), "christmas", "Christmas")
    add(date(y, 12, 26), "christmas", "Boxing Day / 2nd Christmas")
    add(date(y, 12, 31), "new_year_eve", "New Year's Eve")
    add(date(y, 1, 1), "new_year", "New Year")
    add(date(y, 1, 2), "new_year", "New Year (day 2)")
    if end.year > y:
        add(date(y + 1, 1, 1), "new_year", "New Year")
        add(date(y + 1, 12, 25), "christmas", "Christmas")

    events.sort(key=lambda x: x[0])
    return [{"date": d.isoformat(), "id": hid, "label": label} for d, hid, label in events]


def season_key(lang: str, today: date | None = None) -> str:
    today = today or date.today()
    month = f"{today.year}-{today.month:02d}"
    near = upcoming_holidays(lang, today, horizon_days=21)
    # Prefer the closest holiday within 14 days (ahead or just passed).
    pick = ""
    best = 99
    for h in near:
        d = date.fromisoformat(h["date"])
        delta = abs((d - today).days)
        if delta <= 14 and delta < best:
            best = delta
            pick = h["id"]
    return f"{month}|{pick}" if pick else month


def season_brief(lang: str, today: date | None = None) -> str:
    today = today or date.today()
    month_names_en = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_names_ro = [
        "", "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    ]
    names = month_names_ro if lang == "ro" else month_names_en
    lines = [
        f"Today: {today.isoformat()} ({names[today.month]})",
        f"Language preference: {'Romanian' if lang == 'ro' else 'English'} (provide BOTH en and ro for every greeting)",
    ]
    hols = upcoming_holidays(lang, today, 45)
    if hols:
        lines.append("Upcoming / nearby holidays:")
        for h in hols[:8]:
            lines.append(f"  - {h['date']}: {h['label']} (tag={h['id']})")
    else:
        lines.append("No major holidays in the next 45 days — lean seasonal (month mood) + general.")
    # Month mood hints
    mood = {
        12: "winter / Christmas / year-end warmth",
        1: "new year / fresh start / cold",
        2: "late winter / Valentine",
        3: "early spring / Mărțișor (RO)",
        4: "spring / possible Easter",
        5: "late spring",
        6: "early summer",
        7: "summer heat",
        8: "late summer / Assumption (RO)",
        9: "back to school / autumn start",
        10: "autumn / Halloween (EN)",
        11: "late autumn / Sf. Andrei + National Day (RO)",
    }.get(today.month, "general")
    lines.append(f"Month mood: {mood}")
    return "\n".join(lines)


# ── Validation ───────────────────────────────────────────────────────────────

def _clean_item(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tags_in = raw.get("tags") or []
    if not isinstance(tags_in, list):
        return None
    tags = []
    for t in tags_in:
        key = str(t or "").strip().lower()
        if key in ALLOWED_TAGS and key not in tags:
            tags.append(key)
    if not tags:
        tags = ["general"]

    def _pair(obj: Any, fallback: str = "") -> dict[str, str]:
        if isinstance(obj, str) and obj.strip():
            s = obj.strip()[:120]
            return {"en": s, "ro": s}
        if not isinstance(obj, dict):
            return {"en": fallback, "ro": fallback}
        en = str(obj.get("en") or obj.get("ro") or fallback).strip()[:120]
        ro = str(obj.get("ro") or obj.get("en") or fallback).strip()[:120]
        return {"en": en, "ro": ro}

    title = _pair(raw.get("title"))
    hint = _pair(raw.get("hint"))
    if not title["en"] or not hint["en"]:
        return None
    return {"tags": tags, "title": title, "hint": hint}


def public_items(limit: int = 80) -> list[dict]:
    items = load_pool().get("items") or []
    out = []
    for it in items[:limit]:
        cleaned = _clean_item(it)
        if cleaned:
            out.append(cleaned)
    return out


def status_payload(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    block = _cfg_block(cfg)
    pool = load_pool()
    lang = str(cfg.get("language") or "en")
    sk = season_key(lang)
    provider = resolve_greeting_provider(cfg)
    model = resolve_greeting_model(provider, block)
    return {
        "enabled": cfg.get("dynamic_greetings") is not False,
        "refresh_days": block["refresh_days"],
        "pool_size": block["pool_size"],
        "provider_id": block["provider_id"],
        "model": block["model"],
        "resolved_provider_id": provider.get("id") or "",
        "resolved_provider_name": provider.get("name") or "",
        "resolved_model": model or provider.get("model") or "",
        "last_generated_at": block["last_generated_at"] or pool.get("generated_at") or 0,
        "last_season_key": block["last_season_key"] or pool.get("season_key") or "",
        "current_season_key": sk,
        "item_count": len(pool.get("items") or []),
        "status": block["status"],
        "error": block["error"],
        "stale": needs_refresh(cfg),
    }


def needs_refresh(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    if cfg.get("dynamic_greetings") is False:
        return False
    block = _cfg_block(cfg)
    pool = load_pool()
    items = pool.get("items") or []
    if len(items) < 8:
        return True
    lang = str(cfg.get("language") or "en")
    sk = season_key(lang)
    last_sk = block["last_season_key"] or pool.get("season_key") or ""
    if sk != last_sk:
        return True
    last = float(block["last_generated_at"] or pool.get("generated_at") or 0)
    age = time.time() - last
    return age >= block["refresh_days"] * 86400


# ── LLM generation ──────────────────────────────────────────────────────────

_JSON_RE = re.compile(r"\[[\s\S]*\]")


def _parse_llm_items(text: str) -> list[dict]:
    raw = (text or "").strip()
    if not raw:
        return []
    # Strip markdown fences
    if "```" in raw:
        raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        cleaned = _clean_item(row)
        if cleaned:
            out.append(cleaned)
    return out


def _build_prompt(lang: str, pool_size: int) -> str:
    brief = season_brief(lang)
    tags = ", ".join(sorted(ALLOWED_TAGS))
    return f"""You write short welcome greetings for an empty Home Assistant chat UI (HASSAI).
No tools, no markdown, no explanations — ONLY a JSON array.

Context:
{brief}

Write {pool_size} greetings as JSON objects with this shape:
{{"tags":["general","morning"],"title":{{"en":"...","ro":"..."}},"hint":{{"en":"...","ro":"..."}}}}

Rules:
- title: max ~6 words, friendly, not salesy, no emoji spam (0–1 emoji ok)
- hint: one short supporting sentence
- Always fill BOTH en and ro
- tags: only from this set: {tags}
- Cover: ~8 general; 2+ each morning/afternoon/evening/night; several weather tags (rainy, sunny, snowy, cloudy, stormy, cold, hot, clear_night); and several for ANY nearby holidays listed above (use those holiday tags)
- If it is December / late November, lean Christmas / New Year without ignoring general/weather
- If Easter is near, include easter-tagged greetings
- Sound human, varied; no duplicates; no mentioning you are an AI

Return ONLY the JSON array."""


async def regenerate(*, force: bool = False) -> dict:
    """Generate a fresh pool via the active AI provider. Safe to call concurrently."""
    global _gen_lock
    cfg = load_config()
    if cfg.get("dynamic_greetings") is False and not force:
        return status_payload(cfg)
    if _gen_lock:
        block = _cfg_block(cfg)
        block["status"] = "generating"
        return status_payload(cfg)

    _gen_lock = True
    block = _cfg_block(cfg)
    block["status"] = "generating"
    block["error"] = ""
    _save_cfg_block(block)
    lang = str(cfg.get("language") or "en")
    sk = season_key(lang)
    size = block["pool_size"]

    try:
        from services import providers as pv

        provider = resolve_greeting_provider(cfg)
        model = resolve_greeting_model(provider, block)
        messages = [
            {"role": "system", "content": "You are a concise bilingual greeting writer. Output JSON only."},
            {"role": "user", "content": _build_prompt(lang, size)},
        ]
        result = await pv.chat_completion(
            messages,
            model=model,
            stream=False,
            provider=provider,
            thinking={"enabled": False},
            max_tokens=min(4000, 80 * size),
        )
        content = ""
        try:
            content = result["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            content = ""
        if isinstance(content, list):
            # Some providers return content parts
            content = "".join(
                str(p.get("text") or "") for p in content if isinstance(p, dict)
            ) or str(content)

        items = _parse_llm_items(str(content))
        if len(items) < 8:
            raise ValueError(f"LLM returned too few greetings ({len(items)})")

        save_pool(items, season_key=sk)
        block = _cfg_block()
        block["last_generated_at"] = time.time()
        block["last_season_key"] = sk
        block["status"] = "ok"
        block["error"] = ""
        _save_cfg_block(block)
        log.info("Greeting pool refreshed: %s items season=%s", len(items), sk)
        return status_payload()
    except Exception as exc:
        log.warning("Greeting pool generation failed: %s", exc)
        block = _cfg_block()
        block["status"] = "error"
        block["error"] = str(exc)[:300]
        _save_cfg_block(block)
        return status_payload()
    finally:
        _gen_lock = False


async def ensure_fresh(*, force: bool = False) -> dict:
    """Refresh if stale/forced; otherwise return status. Never raises."""
    try:
        cfg = load_config()
        if cfg.get("dynamic_greetings") is False and not force:
            return status_payload(cfg)
        if force or needs_refresh(cfg):
            return await regenerate(force=force)
        return status_payload(cfg)
    except Exception as exc:
        log.debug("ensure_fresh failed: %s", exc)
        return status_payload()
