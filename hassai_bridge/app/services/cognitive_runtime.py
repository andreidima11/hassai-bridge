"""Orchestrate Cognitive OS for one chat turn (called from chat.py)."""

from __future__ import annotations

import logging
import time
from typing import Any

from services import action_compiler as ac
from services import cognitive_kernel as ck
from services import cognitive_metrics as cm
from services import experience_compiler as ec
from services import goal_compiler as gc
from services import working_memory as wmem
from services import world_model as wm

log = logging.getLogger("hassai.cognitive_runtime")


async def prepare_turn(
    *,
    user_text: str,
    user_id: str,
    session_id: str,
    lang: str = "en",
    route_klass: str = "simple",
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Run kernel + reflex/intent beam. Returns a serializable result dict.

    Keys:
      ctx: TurnContext as dict
      handled: bool — True if chat should short-circuit (reflex/clarify)
      message: str — assistant reply when handled
      followups: list — clarification chips
      late_context: str — inject into agent path
      ledger_id: optional
    """
    cfg = cfg or {}
    if not ck.cognitive_enabled(cfg):
        return {"handled": False, "ctx": None, "late_context": "", "followups": []}

    ctx = ck.build_turn_context(
        user_text=user_text,
        user_id=user_id,
        session_id=session_id,
        lang=lang,
        route_klass=route_klass,
        cfg=cfg,
    )
    ctx.working_memory = wmem.load_working_set(user_id, session_id)
    aliases = wmem.list_aliases(user_id)

    # Topic shift: drop sticky lights/areas so the agent doesn't keep controlling them
    if gc.is_topic_shift(user_text):
        wmem.clear_working_set(user_id, session_id)
        ctx.working_memory = wmem.empty_working_set()

    # Only reuse last_entities / last_area for short discourse follow-ups
    wm_for_compile = (
        ctx.working_memory
        if gc.is_discourse_followup(user_text)
        else wmem.empty_working_set()
    )

    # Correction fast-path: learn alias, then let agent/reflex continue next turn
    correction = gc.detect_correction(user_text)
    entities: list[wm.EntityNode] = []
    try:
        entities = await wm.load_entities()
    except Exception:
        log.debug("world model load failed", exc_info=True)

    if correction:
        learned = wmem.apply_correction(
            user_id, session_id, correction, entities=entities,
        )
        ctx.path = ck.PATH_AGENT
        ctx.confidence = 0.9
        ctx.aliases_used = [learned.get("alias")] if learned.get("ok") else []
        ctx.world_snippet = wm.snippet_for_query(
            entities, str(correction.get("prefer") or user_text), limit=8,
        )
        # Prefer re-executing corrected target immediately when resolvable
        if learned.get("ok") and learned.get("resolves_to"):
            prefer_text = (
                f"stinge {learned['resolves_to']}"
                if lang == "ro"
                else f"turn off {learned['resolves_to']}"
            )
            # Keep original verb if present
            intent, _, _ = gc._base_action(user_text)
            if not intent:
                # Infer from working memory last action
                last = ctx.working_memory.get("last_action") or "turn_off"
                intent = last if last in {"turn_on", "turn_off", "open", "close"} else "turn_off"
            if intent == "turn_on":
                prefer_text = f"aprinde {learned['resolves_to']}" if lang == "ro" else f"turn on {learned['resolves_to']}"
            elif intent == "turn_off":
                prefer_text = f"stinge {learned['resolves_to']}" if lang == "ro" else f"turn off {learned['resolves_to']}"
            elif intent == "open":
                prefer_text = f"deschide {learned['resolves_to']}" if lang == "ro" else f"open {learned['resolves_to']}"
            elif intent == "close":
                prefer_text = f"închide {learned['resolves_to']}" if lang == "ro" else f"close {learned['resolves_to']}"
            ctx.user_text = prefer_text
            ctx = ac.compile_reflex(ctx, entities=entities, aliases=aliases)
        else:
            late = ck.late_context_block(ctx)
            cm.record_turn(ctx, outcome={"ok": bool(learned.get("ok")), "correction": correction})
            return {
                "handled": False,
                "ctx": ctx.to_dict(),
                "late_context": late,
                "followups": [],
                "message": "",
            }

    # Active skill match (deterministic)
    skill = ec.match_skill(user_id, user_text, include_shadow=ctx.shadow)
    if skill and skill.get("status") == "active" and ck.reflex_enabled(cfg):
        ck.mark_metric(ctx, "t_action")
        result = await ec.execute_skill(skill, cfg=cfg, shadow=ctx.shadow)
        ctx.path = ck.PATH_SHADOW if ctx.shadow else ck.PATH_SKILL
        ctx.confidence = 0.9
        ctx.metrics["t_action_ms"] = ck.elapsed_ms(ctx, end_key="t_action")
        cm.record_turn(ctx, outcome=result)
        if result.get("ok") and not ctx.shadow:
            wmem.update_after_action(
                user_id, session_id,
                entity_ids=list(skill.get("entity_ids") or []),
                area=str(skill.get("area") or ""),
                action="skill",
            )
            msg = (
                f"Am rulat rutina «{skill.get('trigger')}»."
                if lang == "ro"
                else f"Ran routine “{skill.get('trigger')}”."
            )
            return {
                "handled": True,
                "ctx": ctx.to_dict(),
                "message": msg,
                "followups": [],
                "late_context": "",
                "ledger_id": None,
            }
        if ctx.shadow:
            # Fall through to normal path while logging shadow skill
            pass

    if not ck.reflex_enabled(cfg) or not ac.can_attempt_reflex(ctx.user_text):
        # Still inject world snippet for control-class agent turns
        if route_klass in {"control", "deep"} and entities:
            ctx.world_snippet = wm.snippet_for_query(entities, user_text, limit=10)
            ctx.hypotheses = gc.compile_hypotheses(
                user_text,
                entities=entities,
                working_memory=wm_for_compile,
                aliases=aliases,
            )
            if ctx.hypotheses:
                ctx.goal = gc.goal_from_hypothesis(ctx.hypotheses[0], user_text)
        ctx.path = ck.PATH_AGENT
        # Alias hints for agent
        ctx.aliases_used = [
            {"surface": a.get("surface"), "resolves_to": a.get("resolves_to")}
            for a in aliases[:8]
        ]
        # Don't leak previous light entities into non-follow-up agent turns
        ctx.working_memory = wm_for_compile
        late = ck.late_context_block(ctx)
        cm.record_turn(ctx, outcome={"ok": None, "path": "agent"})
        return {
            "handled": False,
            "ctx": ctx.to_dict(),
            "late_context": late,
            "followups": [],
            "message": "",
        }

    ctx.working_memory = wm_for_compile
    ctx = ac.compile_reflex(ctx, entities=entities, aliases=aliases)
    ctx.aliases_used = [
        {"surface": a.get("surface"), "resolves_to": a.get("resolves_to")}
        for a in aliases[:8]
        if any(
            a.get("resolves_to") in (h.targets or [])
            for h in ctx.hypotheses
        )
    ]

    if ctx.path == ck.PATH_CLARIFY:
        wmem.set_pending_clarification(
            user_id, session_id, ctx.clarification_chips,
            goal=(ctx.goal.goal if ctx.goal else ""),
        )
        cm.record_turn(ctx, outcome={"ok": None, "clarify": True})
        msg = (
            "Care dintre acestea?"
            if lang == "ro"
            else "Which one did you mean?"
        )
        return {
            "handled": True,
            "ctx": ctx.to_dict(),
            "message": msg,
            "followups": ctx.clarification_chips,
            "late_context": "",
            "ledger_id": None,
        }

    if ctx.path in {ck.PATH_REFLEX, ck.PATH_SHADOW}:
        if ctx.path == ck.PATH_SHADOW:
            # Log decision without executing
            hyp = ctx.hypotheses[0] if ctx.hypotheses else None
            cm.record_turn(ctx, outcome={
                "ok": None,
                "shadow": True,
                "would_targets": list(hyp.targets) if hyp else [],
            })
            late = ck.late_context_block(ctx)
            return {
                "handled": False,
                "ctx": ctx.to_dict(),
                "late_context": late,
                "followups": [],
                "message": "",
                "shadow_reflex": True,
            }

        ck.mark_metric(ctx, "t_action")
        result = await ac.execute_reflex(ctx, entities=entities, cfg=cfg)
        ctx.metrics["t_action_ms"] = int((time.time() - float(ctx.metrics.get("t_action") or time.time())) * 1000)
        cm.record_turn(ctx, outcome=result)
        if result.get("ok"):
            hyp = ctx.hypotheses[0]
            wmem.update_after_action(
                user_id, session_id,
                entity_ids=list(result.get("targets") or hyp.targets),
                area=hyp.area,
                action=hyp.intent,
            )
            # Compile experience candidate from reflex trajectory
            try:
                ec.compile_from_trace(
                    user_id=user_id,
                    trigger=user_text,
                    tool_steps=[{
                        "name": "ha_call_service",
                        "args": {
                            "domain": hyp.domain,
                            "service": hyp.service,
                            "entity_id": hyp.targets[0] if hyp.targets else None,
                        },
                    }],
                    entity_ids=list(hyp.targets),
                    area=hyp.area,
                    success=True,
                )
            except Exception:
                log.debug("experience compile failed", exc_info=True)
            undo_chip = []
            if result.get("ledger_id"):
                undo_label = "Anulează" if lang == "ro" else "Undo"
                undo_chip = [{
                    "id": f"undo_{result['ledger_id']}",
                    "label": undo_label,
                    "display_text": undo_label,
                    "prompt": undo_label,  # visible bubble only — never /undo mut_…
                    "topic": "undo",
                    "kind": "undo",
                    "action": {
                        "type": "undo",
                        "ledger_id": result["ledger_id"],
                    },
                }]
            return {
                "handled": True,
                "ctx": ctx.to_dict(),
                "message": result.get("message") or "",
                "followups": undo_chip,
                "late_context": "",
                "ledger_id": result.get("ledger_id"),
            }
        # Policy ask / failure → fall through to agent with context
        ctx.path = ck.PATH_AGENT
        ctx.world_snippet = wm.snippet_for_query(entities, user_text, limit=10)
        late = ck.late_context_block(ctx)
        return {
            "handled": False,
            "ctx": ctx.to_dict(),
            "late_context": late,
            "followups": [],
            "message": "",
            "reflex_error": result.get("error"),
        }

    late = ck.late_context_block(ctx)
    cm.record_turn(ctx, outcome={"ok": None, "path": ctx.path})
    return {
        "handled": False,
        "ctx": ctx.to_dict(),
        "late_context": late,
        "followups": [],
        "message": "",
    }


def note_agent_entities(
    user_id: str,
    session_id: str,
    *,
    entity_ids: list[str],
    area: str = "",
    action: str = "",
) -> None:
    if not entity_ids:
        return
    wmem.update_after_action(
        user_id, session_id,
        entity_ids=entity_ids,
        area=area,
        action=action,
    )
