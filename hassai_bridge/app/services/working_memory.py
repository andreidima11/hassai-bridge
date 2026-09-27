"""Discourse working memory + entity alias lexicon."""

from __future__ import annotations

import logging
import time
from typing import Any

from core import database as db
from services import world_model as wm

log = logging.getLogger("hassai.working_memory")

KIND_WORKING_SET = "working_set"
KIND_DISCOURSE = "discourse"


def load_working_set(user_id: str, session_id: str) -> dict:
    data = db.get_session_state(user_id, session_id, KIND_WORKING_SET) or {}
    return {
        "last_entities": list(data.get("last_entities") or [])[:12],
        "last_area": str(data.get("last_area") or ""),
        "last_action": str(data.get("last_action") or ""),
        "open_goal": str(data.get("open_goal") or ""),
        "pending_clarification": data.get("pending_clarification") or None,
        "updated_at": float(data.get("updated_at") or 0),
    }


def save_working_set(user_id: str, session_id: str, data: dict) -> None:
    payload = {
        "last_entities": list(data.get("last_entities") or [])[:12],
        "last_area": str(data.get("last_area") or "")[:80],
        "last_action": str(data.get("last_action") or "")[:80],
        "open_goal": str(data.get("open_goal") or "")[:200],
        "pending_clarification": data.get("pending_clarification"),
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
    open_goal: str = "",
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
    if open_goal:
        cur["open_goal"] = open_goal
    elif action:
        cur["open_goal"] = ""
    cur["pending_clarification"] = None
    save_working_set(user_id, session_id, cur)
    return cur


def set_pending_clarification(user_id: str, session_id: str, chips: list[dict], goal: str = "") -> None:
    cur = load_working_set(user_id, session_id)
    cur["pending_clarification"] = {"chips": chips[:5], "goal": goal, "ts": time.time()}
    if goal:
        cur["open_goal"] = goal
    save_working_set(user_id, session_id, cur)


# ── Aliases ─────────────────────────────────────────

def list_aliases(user_id: str, *, active_only: bool = True) -> list[dict]:
    return db.list_entity_aliases(user_id, active_only=active_only)


def resolve_alias(user_id: str, surface: str) -> dict | None:
    folded = wm.fold(surface)
    if not folded:
        return None
    for row in list_aliases(user_id):
        if wm.fold(row.get("surface") or "") == folded:
            return row
    # substring match for longer surfaces
    for row in list_aliases(user_id):
        sf = wm.fold(row.get("surface") or "")
        if sf and (sf in folded or folded in sf) and len(sf) >= 3:
            return row
    return None


def learn_alias(
    user_id: str,
    surface: str,
    resolves_to: str,
    *,
    source: str = "correction",
    confidence: float = 0.7,
) -> dict:
    surface = str(surface or "").strip()[:80]
    resolves_to = str(resolves_to or "").strip()[:120]
    if not surface or not resolves_to:
        return {"ok": False, "error": "missing_fields"}
    return db.upsert_entity_alias(
        user_id=user_id,
        surface=surface,
        resolves_to=resolves_to,
        source=source,
        confidence=max(0.1, min(1.0, float(confidence))),
    )


def apply_correction(
    user_id: str,
    session_id: str,
    correction: dict,
    *,
    entities: list | None = None,
) -> dict:
    """Turn a detected correction into an alias + working-set update."""
    from services import goal_compiler as gc

    prefer = str(correction.get("prefer") or "").strip()
    reject = str(correction.get("reject") or "").strip()
    if not prefer:
        return {"ok": False, "error": "no_prefer"}

    # Resolve prefer text to entity via world model search
    target = ""
    if entities:
        hits = wm.search(entities, prefer, limit=3)
        if hits and hits[0][1] >= 2.0:
            target = hits[0][0].entity_id
    if not target:
        # Maybe prefer already is entity_id
        if "." in prefer and " " not in prefer:
            target = prefer

    if not target:
        return {"ok": False, "error": "unresolved_prefer", "prefer": prefer}

    # Learn reject→wrong and prefer→right; surface from reject or prefer nickname
    surface = reject or prefer
    # If user said "nu becul mare, ambientul", surface for ambient is prefer
    alias_surface = prefer if correction.get("kind") == "prefer" else prefer
    row = learn_alias(user_id, alias_surface, target, source="correction", confidence=0.85)
    if reject and reject != prefer:
        # Negative: optionally store reject mapping if we know last wrong entity
        ws = load_working_set(user_id, session_id)
        wrong = (ws.get("last_entities") or [None])[0]
        if wrong and wrong != target:
            learn_alias(user_id, reject, target, source="correction_reject", confidence=0.6)

    update_after_action(
        user_id, session_id,
        entity_ids=[target],
        action="correction",
        open_goal="",
    )
    return {"ok": True, "alias": row, "resolves_to": target}


def discourse_block(user_id: str, session_id: str) -> dict[str, Any]:
    ws = load_working_set(user_id, session_id)
    return ws
