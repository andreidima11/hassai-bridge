"""Discourse working memory + learned entity names.

The working set records what was last acted on. It is *described* to the
model as text ("Recent actions: turned on Lampa Dormitor 1, 40s ago") and
never used to pick a target on the model's behalf.

Aliases are a resolution cache: once the agent has resolved a short command
("aprinde bec balcon") to exactly one entity, the phrase → entity pair is
remembered so the next identical command can be a reflex.
"""

from __future__ import annotations

import logging
import time

from core import database as db
from services import world_model as wm

log = logging.getLogger("hassai.working_memory")

KIND_WORKING_SET = "working_set"

_ALIAS_SURFACE_MAX = 80
_ALIAS_MIN_CHARS = 3


def load_working_set(user_id: str, session_id: str) -> dict:
    data = db.get_session_state(user_id, session_id, KIND_WORKING_SET) or {}
    return {
        "last_entities": list(data.get("last_entities") or [])[:12],
        "last_area": str(data.get("last_area") or ""),
        "last_action": str(data.get("last_action") or ""),
        "updated_at": float(data.get("updated_at") or 0),
    }


def save_working_set(user_id: str, session_id: str, data: dict) -> None:
    payload = {
        "last_entities": list(data.get("last_entities") or [])[:12],
        "last_area": str(data.get("last_area") or "")[:80],
        "last_action": str(data.get("last_action") or "")[:80],
        "updated_at": time.time(),
    }
    db.upsert_session_state(user_id, session_id, KIND_WORKING_SET, payload)


def update_after_action(
    user_id: str,
    session_id: str,
    *,
    entity_ids: list[str] | None = None,
    area: str = "",
    action: str = "",
) -> dict:
    cur = load_working_set(user_id, session_id)
    if entity_ids:
        merged = []
        for e in list(entity_ids) + list(cur.get("last_entities") or []):
            if e and e not in merged:
                merged.append(e)
        cur["last_entities"] = merged[:12]
    if area:
        cur["last_area"] = area
    if action:
        cur["last_action"] = action
    save_working_set(user_id, session_id, cur)
    return cur


def recent_actions_text(
    working_set: dict,
    entities: list[wm.EntityNode],
    *,
    lang: str = "en",
    max_age_s: float = 15 * 60,
    now: float | None = None,
) -> str:
    """Human-readable recap of the last action for the model's context."""
    if not working_set:
        return ""
    updated = float(working_set.get("updated_at") or 0)
    now = now if now is not None else time.time()
    if not updated or now - updated > max_age_s:
        return ""
    ids = [str(e) for e in (working_set.get("last_entities") or [])[:4]]
    if not ids:
        return ""
    names = []
    for eid in ids:
        node = wm.by_id(entities, eid)
        if node:
            area = f" ({node.area})" if node.area else ""
            names.append(f"{node.name}{area} [{eid}]")
        else:
            names.append(eid)
    age = max(0, int(now - updated))
    age_txt = f"{age}s" if age < 90 else f"{age // 60}min"
    action = str(working_set.get("last_action") or "").replace("_", " ") or (
        "acționat" if lang == "ro" else "acted on"
    )
    if lang == "ro":
        return f"Ultima acțiune ({age_txt} în urmă): {action} — {', '.join(names)}."
    return f"Last action ({age_txt} ago): {action} — {', '.join(names)}."


# ── Aliases (resolution cache) ─────────────────────────


def list_aliases(user_id: str, *, active_only: bool = True) -> list[dict]:
    return db.list_entity_aliases(user_id, active_only=active_only)


def learn_alias(
    user_id: str,
    surface: str,
    resolves_to: str,
    *,
    source: str = "agent",
    confidence: float = 0.7,
) -> dict:
    surface = wm.fold(surface)[:_ALIAS_SURFACE_MAX]
    resolves_to = str(resolves_to or "").strip()[:120]
    if len(surface) < _ALIAS_MIN_CHARS or not resolves_to:
        return {"ok": False, "error": "missing_fields"}
    return db.upsert_entity_alias(
        user_id=user_id,
        surface=surface,
        resolves_to=resolves_to,
        source=source,
        confidence=max(0.1, min(1.0, float(confidence))),
    )


def find_alias(aliases: list[dict], phrase: str) -> str:
    """entity_id for an exact (folded) alias surface, else ``""``."""
    needle = wm.fold(phrase)
    if not needle:
        return ""
    for row in aliases:
        if wm.fold(str(row.get("surface") or "")) == needle:
            return str(row.get("resolves_to") or "")
    return ""
