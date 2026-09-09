"""Conversation-derived habits for recommendation chips (not HA logbook, not fact memory)."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from core.config import load_config
from core.database import get_db

log = logging.getLogger("hassai.chat_habits")

WEIGHTS = {
    "chip_click": 3.0,
    "user_ask": 2.0,
    "followup_yes": 1.0,
    "backfill": 0.5,
}

_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("flood", re.compile(r"\binunda", re.I)),
    ("batteries", re.compile(r"\bbateri", re.I)),
    ("irrigation", re.compile(r"\biriga", re.I)),
    ("solar", re.compile(r"\b(?:solar|produc(?:ție|tie)|pv\b|kwh|energie|energy)", re.I)),
    ("gates", re.compile(r"\b(?:poart|garaj|gate)", re.I)),
    ("lights", re.compile(r"\b(?:lumin|aprins|stinge|aprinde)", re.I)),
    ("climate", re.compile(r"\b(?:climat|termostat|temperatur|aer\s+cond)", re.I)),
    ("cameras", re.compile(r"\b(?:frigate|camer[aă]|detec)", re.I)),
    ("weather", re.compile(r"\b(?:vremea|weather)", re.I)),
    ("house_status", re.compile(r"\b(?:status\s+cas|home\s+status|statusul\s+casei)", re.I)),
    ("energy", re.compile(r"\b(?:consum|curent|produc)", re.I)),
]

_CHIP_ID_TOPIC = {
    "fu-topic-flood": "flood",
    "fu-topic-battery": "batteries",
    "fu-topic-irrigation": "irrigation",
    "fu-topic-solar": "solar",
    "fu-topic-gates": "gates",
    "fu-topic-lights": "lights",
    "fu-topic-climate": "climate",
    "fu-topic-cameras": "cameras",
    "energy-today": "solar",
    "house-status": "house_status",
    "weather": "weather",
    "list-lights": "lights",
}

_TOPIC_LABELS = {
    "flood": {
        "ro": ("Senzori inundație", "Verifică mai detaliat senzorii de inundație."),
        "en": ("Flood sensors", "Check the flood sensors in more detail."),
    },
    "batteries": {
        "ro": ("Baterii slabe", "Detaliază bateriile slabe și ce merită înlocuit."),
        "en": ("Low batteries", "Detail the low batteries and what to replace."),
    },
    "irrigation": {
        "ro": ("Irigații", "Detaliază irigațiile — ce zone au rulat și când."),
        "en": ("Irrigation", "Detail the irrigation — which zones ran and when."),
    },
    "solar": {
        "ro": ("Producție solară", "Spune-mi mai multe despre producția solară de azi."),
        "en": ("Solar production", "Tell me more about today's solar production."),
    },
    "gates": {
        "ro": ("Porți", "Verifică porțile — ce e deschis și ce merită făcut."),
        "en": ("Gates", "Check the gates — what's open and what to do."),
    },
    "lights": {
        "ro": ("Lumini", "Ce lumini sunt aprinse acum?"),
        "en": ("Lights", "Which lights are on right now?"),
    },
    "climate": {
        "ro": ("Climă", "Detaliază clima / termostatele acum."),
        "en": ("Climate", "Detail the climate / thermostats right now."),
    },
    "cameras": {
        "ro": ("Camere", "Verifică detecțiile recente de pe camere."),
        "en": ("Cameras", "Check recent camera detections."),
    },
    "house_status": {
        "ro": ("Status casă", "Dă-mi pe scurt statusul casei."),
        "en": ("Home status", "Give me a short home status."),
    },
    "energy": {
        "ro": ("Energie", "Cât curent / energie am produs sau consumat azi?"),
        "en": ("Energy", "How much energy did I produce or use today?"),
    },
    "weather": {
        "ro": ("Vremea", "Cum e vremea acum acasă?"),
        "en": ("Weather", "What's the weather like at home?"),
    },
}

_YES_PREFIX = re.compile(r"^\s*(?:da|yes)\s*[—\-–:]\s*", re.I)
_BACKFILL_FLAG = "chat_habits_backfill_v1"


def learn_from_chat_enabled(cfg: dict | None = None) -> bool:
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    rec = cfg.get("recommendations") if isinstance(cfg.get("recommendations"), dict) else {}
    if not isinstance(rec, dict):
        return False
    if rec.get("enabled") is False:
        return False
    mode = str(rec.get("mode") or "medium").strip().lower()
    if mode in {"none", "off", "disabled"}:
        return False
    if "learn_from_chat" in rec:
        return bool(rec.get("learn_from_chat"))
    return True


def classify_topic(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for topic, pattern in _TOPIC_PATTERNS:
        if pattern.search(raw):
            return topic
    return None


def topic_from_chip(chip: dict | None) -> str | None:
    if not isinstance(chip, dict):
        return None
    cid = str(chip.get("id") or "")
    if cid in _CHIP_ID_TOPIC:
        return _CHIP_ID_TOPIC[cid]
    if cid.startswith("on-") or cid.startswith("off-"):
        return "lights"
    if cid.startswith("open-") or cid.startswith("close-"):
        return "gates"
    if cid.startswith("ac-") or cid.startswith("heat-") or cid.startswith("cool-"):
        return "climate"
    blob = f"{chip.get('label') or ''} {chip.get('prompt') or ''}"
    return classify_topic(blob)


def topic_labels(topic: str, lang: str = "en") -> tuple[str, str] | None:
    meta = _TOPIC_LABELS.get(topic)
    if not meta:
        return None
    return meta.get(lang) or meta["en"]


def record(
    user_id: str,
    *,
    topic: str,
    hour: int | None = None,
    after_intent: str = "",
    source: str = "user_ask",
    weight: float | None = None,
) -> None:
    if not user_id or not topic or topic == "other":
        return
    if not learn_from_chat_enabled():
        return
    hour = datetime.now().astimezone().hour if hour is None else int(hour) % 24
    after_intent = str(after_intent or "")[:40]
    source = str(source or "user_ask")[:40]
    w = float(WEIGHTS.get(source, 1.0) if weight is None else weight)
    if w <= 0:
        return
    now = time.time()
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO chat_habits (user_id, topic, hour, after_intent, source, count, last_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, topic, hour, after_intent, source) DO UPDATE SET
                    count = count + excluded.count,
                    last_at = excluded.last_at
                """,
                (user_id, topic, hour, after_intent, source, w, now),
            )
    except Exception as e:
        log.debug("chat_habits record failed: %s", e)


def record_from_chip(
    user_id: str,
    chip: dict,
    *,
    context: str = "empty",
    after_intent: str = "",
    hour: int | None = None,
) -> None:
    topic = topic_from_chip(chip)
    prompt = str(chip.get("prompt") or "")
    source = "chip_click"
    if _YES_PREFIX.match(prompt) or str(chip.get("id") or "") == "fu-yes":
        source = "followup_yes"
        if not topic:
            topic = classify_topic(prompt)
    if not topic:
        return
    after = after_intent
    if context == "followup" and not after:
        after = "status" if topic in {"irrigation", "batteries", "flood", "solar"} else ""
    record(user_id, topic=topic, hour=hour, after_intent=after, source=source)


def record_user_text(
    user_id: str,
    text: str,
    *,
    after_intent: str = "",
    hour: int | None = None,
) -> None:
    raw = (text or "").strip()
    if not raw:
        return
    source = "user_ask"
    if _YES_PREFIX.match(raw):
        source = "followup_yes"
    topic = classify_topic(raw)
    if not topic:
        return
    record(user_id, topic=topic, hour=hour, after_intent=after_intent or "", source=source)


def top_topics_for_hour(
    user_id: str,
    *,
    hour: int | None = None,
    limit: int = 5,
) -> list[tuple[str, float]]:
    if not user_id or not learn_from_chat_enabled():
        return []
    hour = datetime.now().astimezone().hour if hour is None else int(hour) % 24
    neighbors = {(hour - 1) % 24, hour, (hour + 1) % 24}
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT topic, hour, SUM(count) AS c
                FROM chat_habits
                WHERE user_id = ?
                GROUP BY topic, hour
                """,
                (user_id,),
            ).fetchall()
    except Exception as e:
        log.debug("chat_habits top_topics failed: %s", e)
        return []
    scores: dict[str, float] = {}
    for row in rows:
        topic = str(row["topic"] or "")
        h = int(row["hour"] or 0)
        c = float(row["c"] or 0)
        if not topic:
            continue
        if h == hour:
            scores[topic] = scores.get(topic, 0) + c * 5
        elif h in neighbors:
            scores[topic] = scores.get(topic, 0) + c * 3
        else:
            scores[topic] = scores.get(topic, 0) + c * 0.2
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(t, s) for t, s in ranked if s > 0][:limit]


def topics_after(
    user_id: str,
    intent: str,
    *,
    hour: int | None = None,
    limit: int = 5,
) -> list[tuple[str, float]]:
    if not user_id or not learn_from_chat_enabled():
        return []
    if not intent:
        return top_topics_for_hour(user_id, hour=hour, limit=limit)
    hour = datetime.now().astimezone().hour if hour is None else int(hour) % 24
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT topic, hour, SUM(count) AS c
                FROM chat_habits
                WHERE user_id = ? AND after_intent = ?
                GROUP BY topic, hour
                """,
                (user_id, intent),
            ).fetchall()
    except Exception as e:
        log.debug("chat_habits topics_after failed: %s", e)
        return top_topics_for_hour(user_id, hour=hour, limit=limit)
    if not rows:
        return top_topics_for_hour(user_id, hour=hour, limit=limit)
    scores: dict[str, float] = {}
    for row in rows:
        topic = str(row["topic"] or "")
        h = int(row["hour"] or 0)
        c = float(row["c"] or 0)
        mult = 5 if h == hour else (3 if abs(h - hour) % 24 <= 1 or abs(h - hour) % 24 >= 23 else 1)
        scores[topic] = scores.get(topic, 0) + c * mult
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(t, s) for t, s in ranked if s > 0][:limit]


def clear_for_user(user_id: str) -> int:
    if not user_id:
        return 0
    with get_db() as conn:
        cur = conn.execute("DELETE FROM chat_habits WHERE user_id = ?", (user_id,))
        return int(cur.rowcount or 0)


def clear_topic(user_id: str, topic: str) -> int:
    if not user_id or not topic:
        return 0
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM chat_habits WHERE user_id = ? AND topic = ?",
            (user_id, str(topic)[:40]),
        )
        return int(cur.rowcount or 0)


def list_patterns(user_id: str, *, limit: int = 30) -> list[dict]:
    """Aggregated habit topics for Settings UI."""
    if not user_id:
        return []
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT topic, SUM(count) AS c, MAX(last_at) AS last_at,
                       GROUP_CONCAT(DISTINCT hour) AS hours
                FROM chat_habits
                WHERE user_id = ?
                GROUP BY topic
                ORDER BY c DESC
                LIMIT ?
                """,
                (user_id, int(limit)),
            ).fetchall()
    except Exception as e:
        log.debug("chat_habits list_patterns failed: %s", e)
        return []
    out = []
    for row in rows:
        topic = str(row["topic"] or "")
        if not topic:
            continue
        hours_raw = str(row["hours"] or "")
        hours = sorted({int(h) for h in hours_raw.split(",") if h.strip().isdigit()})
        labels = topic_labels(topic, "en")
        out.append({
            "topic": topic,
            "score": round(float(row["c"] or 0), 2),
            "last_at": float(row["last_at"] or 0),
            "hours": hours[:12],
            "label": (labels[0] if labels else topic),
        })
    return out


def preference_topic_boosts(user_id: str) -> dict[str, float]:
    """Soft boosts from long-term preference/instruction memories."""
    if not user_id or not learn_from_chat_enabled():
        return {}
    try:
        from core.database import get_memories_by_category
    except Exception:
        return {}
    boosts: dict[str, float] = {}
    for cat in ("preferences", "instructions"):
        try:
            rows = get_memories_by_category(user_id, cat) or []
        except Exception:
            rows = []
        for mem in rows:
            content = str(mem.get("content") or "") if isinstance(mem, dict) else str(mem)
            topic = classify_topic(content)
            if topic:
                boosts[topic] = boosts.get(topic, 0) + 4.0
    return boosts


def _backfill_done(user_id: str) -> bool:
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT 1 FROM chat_habits_meta WHERE user_id = ? AND key = ?",
                (user_id, _BACKFILL_FLAG),
            ).fetchone()
            return row is not None
    except Exception:
        return True


def _mark_backfill_done(user_id: str) -> None:
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO chat_habits_meta (user_id, key, value, updated_at)
                VALUES (?, ?, '1', ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value = '1', updated_at = excluded.updated_at
                """,
                (user_id, _BACKFILL_FLAG, time.time()),
            )
    except Exception as e:
        log.debug("chat_habits backfill flag failed: %s", e)


def backfill_from_conversations(user_id: str, *, days: int = 14) -> int:
    """One-shot classify recent user messages into chat_habits."""
    if not user_id or not learn_from_chat_enabled():
        return 0
    if _backfill_done(user_id):
        return 0
    cutoff = time.time() - max(1, days) * 86400
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT content, created_at FROM conversations
                WHERE user_id = ? AND role = 'user' AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 500
                """,
                (user_id, cutoff),
            ).fetchall()
    except Exception as e:
        log.debug("chat_habits backfill read failed: %s", e)
        _mark_backfill_done(user_id)
        return 0
    n = 0
    for row in rows:
        text = str(row["content"] or "")
        topic = classify_topic(text)
        if not topic:
            continue
        try:
            hour = datetime.fromtimestamp(float(row["created_at"])).astimezone().hour
        except Exception:
            hour = datetime.now().astimezone().hour
        record(
            user_id,
            topic=topic,
            hour=hour,
            after_intent="",
            source="backfill",
            weight=WEIGHTS["backfill"],
        )
        n += 1
    _mark_backfill_done(user_id)
    if n:
        log.info("chat_habits backfill user=%s rows=%s", user_id, n)
    return n
