"""Compile successful tool trajectories into parameterized household skills.

Skills start in shadow mode and are promoted only after enough concordant
successes (or explicit user confirmation).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from core import database as db
from services import world_model as wm

log = logging.getLogger("hassai.experience")

STATUS_SHADOW = "shadow"
STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"

_PROMOTE_SUCCESSES = 3
_PROMOTE_MIN_RATE = 0.8


def _slug(text: str) -> str:
    folded = wm.fold(text)
    slug = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    return (slug or "skill")[:48]


def skill_id_for(trigger: str) -> str:
    return f"skill_{_slug(trigger)}_{uuid.uuid4().hex[:6]}"


def compile_from_trace(
    *,
    user_id: str,
    trigger: str,
    tool_steps: list[dict],
    entity_ids: list[str] | None = None,
    area: str = "",
    success: bool = True,
) -> dict | None:
    """Create or reinforce a skill candidate from a successful trajectory."""
    trigger = str(trigger or "").strip()
    if not trigger or not success:
        return None
    steps = []
    for step in tool_steps or []:
        name = str(step.get("name") or step.get("tool") or "").strip()
        if not name:
            continue
        steps.append({
            "tool": name,
            "args": step.get("args") or step.get("arguments") or {},
        })
    if len(steps) < 1:
        return None

    # Prefer reinforcing an existing active/shadow skill with same trigger fold
    existing = db.find_experience_skill(user_id, trigger)
    if existing:
        return db.touch_experience_skill(
            existing["skill_id"],
            success=True,
            steps=steps,
            entity_ids=entity_ids or existing.get("entity_ids") or [],
        )

    sid = skill_id_for(trigger)
    recipe = {
        "steps": steps,
        "params": {
            "area": area,
            "entity_ids": list(entity_ids or [])[:12],
        },
        "preconditions": [],
        "verify": [],
        "policy": "allow",
    }
    return db.insert_experience_skill(
        skill_id=sid,
        user_id=user_id,
        trigger=trigger,
        recipe=recipe,
        status=STATUS_SHADOW,
        entity_ids=list(entity_ids or [])[:12],
        area=area,
    )


def maybe_promote(skill_id: str) -> dict | None:
    row = db.get_experience_skill(skill_id)
    if not row or row.get("status") != STATUS_SHADOW:
        return row
    successes = int(row.get("success_count") or 0)
    attempts = int(row.get("attempt_count") or 0) or successes
    rate = successes / max(1, attempts)
    if successes >= _PROMOTE_SUCCESSES and rate >= _PROMOTE_MIN_RATE:
        return db.set_experience_skill_status(skill_id, STATUS_ACTIVE)
    return row


def match_skill(user_id: str, user_text: str, *, include_shadow: bool = False) -> dict | None:
    folded = wm.fold(user_text)
    if not folded:
        return None
    statuses = [STATUS_ACTIVE]
    if include_shadow:
        statuses.append(STATUS_SHADOW)
    best = None
    best_score = 0.0
    for row in db.list_experience_skills(user_id, statuses=statuses):
        trig = wm.fold(row.get("trigger") or "")
        if not trig:
            continue
        if trig == folded:
            score = 1.0
        elif trig in folded or folded in trig:
            score = 0.85
        else:
            # token overlap
            tt = set(wm.tokenize(trig))
            ut = set(wm.tokenize(folded))
            if not tt or not ut:
                continue
            score = len(tt & ut) / max(len(tt), len(ut))
            if score < 0.7:
                continue
        if score > best_score:
            best_score = score
            best = row
    return best if best_score >= 0.7 else None


async def run_skill_shadow(skill: dict, *, user_text: str) -> dict:
    """Produce the decision a skill would make without executing."""
    recipe = skill.get("recipe") if isinstance(skill.get("recipe"), dict) else {}
    steps = list(recipe.get("steps") or [])
    return {
        "ok": True,
        "shadow": True,
        "skill_id": skill.get("skill_id"),
        "status": skill.get("status"),
        "would_run_steps": len(steps),
        "steps": steps[:12],
        "trigger": skill.get("trigger"),
        "matched_text": user_text,
    }


async def execute_skill(
    skill: dict,
    *,
    cfg: dict | None = None,
    shadow: bool = False,
) -> dict:
    if shadow or skill.get("status") == STATUS_SHADOW:
        return await run_skill_shadow(skill, user_text=str(skill.get("trigger") or ""))

    from services import homeassistant as ha
    from services import autonomy_policy as ap

    recipe = skill.get("recipe") if isinstance(skill.get("recipe"), dict) else {}
    steps = list(recipe.get("steps") or [])
    results = []
    for step in steps:
        tool = str(step.get("tool") or "")
        args = dict(step.get("args") or {})
        if tool == "ha_call_service":
            decision = ap.decide(
                tool=tool,
                domain=str(args.get("domain") or ""),
                service=str(args.get("service") or ""),
                entity_ids=[args.get("entity_id")] if args.get("entity_id") else (
                    (args.get("data") or {}).get("entity_id")
                    if isinstance(args.get("data"), dict) else None
                ),
                cfg=cfg,
            )
            if decision != "allow":
                db.touch_experience_skill(skill["skill_id"], success=False)
                return {"ok": False, "error": f"policy_{decision}", "results": results}
        try:
            out = await ha.run_ha_tool(tool, args, cfg=cfg) if tool.startswith("ha_") else f"skip:{tool}"
        except Exception as exc:
            db.touch_experience_skill(skill["skill_id"], success=False)
            return {"ok": False, "error": str(exc), "results": results}
        results.append({"tool": tool, "result": out})
        if isinstance(out, str) and out.startswith("Error"):
            db.touch_experience_skill(skill["skill_id"], success=False)
            return {"ok": False, "error": out, "results": results}

    db.touch_experience_skill(skill["skill_id"], success=True)
    maybe_promote(skill["skill_id"])
    return {"ok": True, "skill_id": skill["skill_id"], "results": results}
