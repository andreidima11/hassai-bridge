"""Orchestrate Cognitive OS for one chat turn (called from chat.py)."""

from __future__ import annotations

import logging
from typing import Any

from services import action_compiler as ac
from services import cognitive_kernel as ck
from services import cognitive_metrics as cm
from services import experience_compiler as ec
from services import goal_compiler as gc
from services import working_memory as wmem
from services import world_model as wm

log = logging.getLogger("hassai.cognitive_runtime")

# Route classes whose turns usually touch devices → inject the house index.
_CONTROL_ROUTES = frozenset({"control", "deep"})
_INDEX_LIMIT = 100


def _agent_result(ctx: ck.TurnContext, **extra: Any) -> dict[str, Any]:
    return {
        "handled": False,
        "ctx": ctx.to_dict(),
        "late_context": ck.late_context_block(ctx),
        "followups": [],
        "message": "",
        **extra,
    }


def _undo_chip(ledger_id: str, lang: str) -> dict:
    label = "Anulează" if lang == "ro" else "Undo"
    return {
        "id": f"undo_{ledger_id}",
        "label": label,
        "display_text": label,
        "prompt": label,  # visible bubble only — never a slash command
        "topic": "undo",
        "kind": "undo",
        "action": {"type": "undo", "ledger_id": ledger_id},
    }


async def prepare_turn(
    *,
    user_text: str,
    user_id: str,
    session_id: str,
    lang: str = "en",
    route_klass: str = "simple",
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Run skill/reflex checks and build agent context.

    Keys:
      ctx: TurnContext as dict
      handled: bool — True if chat should short-circuit (skill or reflex ran)
      message: str — assistant reply when handled
      followups: list — structured chips (Undo)
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

    entities: list[wm.EntityNode] = []
    try:
        entities = await wm.load_entities()
    except Exception:
        log.debug("world model load failed", exc_info=True)

    ctx.recent_actions_text = wmem.recent_actions_text(
        ctx.working_memory, entities, lang=ctx.lang,
    )
    ctx.aliases_used = [
        {"surface": a.get("surface"), "resolves_to": a.get("resolves_to")}
        for a in aliases[:8]
    ]

    # Deterministic skill — exact trigger only.
    skill = ec.match_skill(user_id, user_text, include_shadow=ctx.shadow)
    if skill and skill.get("status") == ec.STATUS_ACTIVE and ck.reflex_enabled(cfg):
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
                if ctx.lang == "ro"
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

    # Reflex — exact target only; otherwise the agent gets the house index.
    if ck.reflex_enabled(cfg):
        ctx = ac.compile_reflex(ctx, entities=entities, aliases=aliases)

    if ctx.path in {ck.PATH_REFLEX, ck.PATH_SHADOW} and ctx.hypotheses:
        hyp = ctx.hypotheses[0]
        if ctx.path == ck.PATH_SHADOW:
            cm.record_turn(ctx, outcome={
                "ok": None, "shadow": True, "would_targets": list(hyp.targets),
            })
            _inject_index(ctx, entities, route_klass)
            return _agent_result(ctx, shadow_reflex=True)

        ck.mark_metric(ctx, "t_action")
        result = await ac.execute_reflex(ctx, entities=entities, cfg=cfg)
        ctx.metrics["t_action_ms"] = ck.elapsed_ms(ctx, end_key="t_action")
        cm.record_turn(ctx, outcome=result)
        if result.get("ok"):
            wmem.update_after_action(
                user_id, session_id,
                entity_ids=list(result.get("targets") or hyp.targets),
                area=hyp.area,
                action=hyp.intent,
            )
            try:
                ec.compile_from_trace(
                    user_id=user_id,
                    trigger=user_text,
                    tool_steps=[{
                        "name": "ha_call_service",
                        "args": {
                            "domain": hyp.domain,
                            "service": hyp.service,
                            "entity_id": hyp.targets[0],
                        },
                    }],
                    entity_ids=list(hyp.targets),
                    area=hyp.area,
                    success=True,
                )
            except Exception:
                log.debug("experience compile failed", exc_info=True)
            ledger_id = result.get("ledger_id")
            return {
                "handled": True,
                "ctx": ctx.to_dict(),
                "message": result.get("message") or "",
                "followups": [_undo_chip(ledger_id, ctx.lang)] if ledger_id else [],
                "late_context": "",
                "ledger_id": ledger_id,
            }
        # Policy ask / HA failure → agent continues with full context.
        ctx.path = ck.PATH_AGENT
        _inject_index(ctx, entities, route_klass)
        return _agent_result(ctx, reflex_error=result.get("error"))

    ctx.path = ck.PATH_AGENT
    _inject_index(ctx, entities, route_klass)
    cm.record_turn(ctx, outcome={"ok": None, "path": "agent"})
    return _agent_result(ctx)


def _inject_index(ctx: ck.TurnContext, entities: list[wm.EntityNode], route_klass: str) -> None:
    """Give the agent the full controllable index when the turn is about devices."""
    if not entities:
        return
    if route_klass in _CONTROL_ROUTES or ac.can_attempt_reflex(ctx.user_text):
        ctx.world_snippet = wm.index_block(entities, limit=_INDEX_LIMIT)


def note_agent_entities(
    user_id: str,
    session_id: str,
    *,
    entity_ids: list[str],
    area: str = "",
    action: str = "",
    user_text: str = "",
) -> None:
    """Record what the agent acted on; learn the phrase → entity mapping when
    a short command resolved to exactly one entity so it becomes a reflex."""
    if not entity_ids:
        return
    wmem.update_after_action(
        user_id, session_id,
        entity_ids=entity_ids,
        area=area,
        action=action,
    )
    if len(entity_ids) != 1 or not user_text:
        return
    try:
        intent, _, phrase = gc.parse_command(user_text)
        if not intent or not phrase or len(phrase) > 60:
            return
        if phrase.lower() == entity_ids[0].lower():
            return
        wmem.learn_alias(user_id, phrase, entity_ids[0], source="agent", confidence=0.7)
    except Exception:
        log.debug("alias learning failed", exc_info=True)
