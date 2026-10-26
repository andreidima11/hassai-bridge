"""Reflex Tier 0 — execute short HA commands without an LLM round-trip.

The reflex fires only when the target is *certain*:

* the message is ``<verb> <phrase>`` with a verb from the intent lexicon, and
* ``<phrase>`` is a learned alias, a raw ``entity_id``, or equals exactly one
  entity's friendly name (optionally followed by its area).

Anything else — partial names, several matches, pronouns, questions — goes to
the agent with the house index in context. The reflex never asks "which one?".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from services.cognitive_kernel import (
    PATH_AGENT,
    PATH_REFLEX,
    PATH_SHADOW,
    Hypothesis,
    TurnContext,
)
from services import goal_compiler as gc
from services import world_model as wm

log = logging.getLogger("hassai.action_compiler")

_SHORT_MAX = 140
_ENTITY_ID_RE = re.compile(r"^([a-z_]+)\.([a-z0-9_]+)$", re.I)

# Which intents make sense for which domain (and the service they map to).
_SERVICE_TABLE: dict[str, dict[str, str]] = {
    "light": {"turn_on": "turn_on", "turn_off": "turn_off", "toggle": "toggle",
              "open": "turn_on", "close": "turn_off"},
    "switch": {"turn_on": "turn_on", "turn_off": "turn_off", "toggle": "toggle",
               "open": "turn_on", "close": "turn_off"},
    "fan": {"turn_on": "turn_on", "turn_off": "turn_off", "toggle": "toggle"},
    "input_boolean": {"turn_on": "turn_on", "turn_off": "turn_off", "toggle": "toggle"},
    "scene": {"turn_on": "turn_on", "open": "turn_on"},
    "script": {"turn_on": "turn_on", "open": "turn_on", "turn_off": "turn_off"},
    "vacuum": {"turn_on": "start", "turn_off": "return_to_base", "pause": "pause"},
    "cover": {"open": "open_cover", "close": "close_cover",
              "turn_on": "open_cover", "turn_off": "close_cover", "toggle": "toggle"},
    "lock": {"lock": "lock", "unlock": "unlock", "close": "lock", "open": "unlock"},
    "media_player": {"turn_on": "turn_on", "turn_off": "turn_off", "pause": "media_pause",
                     "toggle": "toggle", "close": "turn_off"},
    "climate": {"turn_on": "turn_on", "turn_off": "turn_off"},
}

# Expected state after the service, when it differs from the generic one.
_EXPECTED_BY_DOMAIN: dict[str, dict[str, str]] = {
    "cover": {"open": "open", "close": "closed", "turn_on": "open", "turn_off": "closed"},
    "lock": {"lock": "locked", "unlock": "unlocked", "close": "locked", "open": "unlocked"},
    "vacuum": {"turn_on": "cleaning", "turn_off": "returning"},
}


def can_attempt_reflex(user_text: str) -> bool:
    text = " ".join(str(user_text or "").split())
    if not text or len(text) > _SHORT_MAX:
        return False
    from services import deepseek as ds
    from services import tool_awareness as taw

    if ds.looks_like_automation_edit(text) or taw.looks_like_explain_event(text):
        return False
    return bool(gc.parse_command(text)[0])


def service_for_hypothesis(hyp: Hypothesis) -> tuple[str, str, dict]:
    """Map hypothesis → (domain, service, data). Empty service = not a reflex."""
    targets = list(hyp.targets or [])
    if not targets:
        return "", "", {}
    domain = targets[0].split(".", 1)[0]
    service = _SERVICE_TABLE.get(domain, {}).get(hyp.intent, "")
    return domain, service, {}


def expected_state_for(domain: str, intent: str, default: str) -> str:
    return _EXPECTED_BY_DOMAIN.get(domain, {}).get(intent, default)


def confirmation_text(
    hyp: Hypothesis,
    *,
    lang: str = "en",
    entities: list[wm.EntityNode] | None = None,
) -> str:
    names: list[str] = []
    for eid in hyp.targets[:4]:
        node = wm.by_id(entities or [], eid)
        names.append(node.name if node else eid.split(".", 1)[-1].replace("_", " "))
    target = ", ".join(names) if names else (hyp.area or "device")
    area_bit = ""
    if hyp.area:
        area_bit = f" din {hyp.area}" if lang == "ro" else f" in {hyp.area}"
    if lang == "ro":
        mapping = {
            "turn_on": f"Am aprins {target}{area_bit}.",
            "turn_off": f"Am stins {target}{area_bit}.",
            "toggle": f"Am comutat {target}{area_bit}.",
            "open": f"Am deschis {target}{area_bit}.",
            "close": f"Am închis {target}{area_bit}.",
            "lock": f"Am încuiat {target}{area_bit}.",
            "unlock": f"Am descuiat {target}{area_bit}.",
            "pause": f"Am pus pauză la {target}.",
        }
        return mapping.get(hyp.intent, f"Gata: {target}.")
    mapping = {
        "turn_on": f"Turned on {target}{area_bit}.",
        "turn_off": f"Turned off {target}{area_bit}.",
        "toggle": f"Toggled {target}{area_bit}.",
        "open": f"Opened {target}{area_bit}.",
        "close": f"Closed {target}{area_bit}.",
        "lock": f"Locked {target}{area_bit}.",
        "unlock": f"Unlocked {target}{area_bit}.",
        "pause": f"Paused {target}.",
    }
    return mapping.get(hyp.intent, f"Done: {target}.")


def resolve_target(
    phrase: str,
    *,
    entities: list[wm.EntityNode],
    aliases: list[dict] | None = None,
) -> tuple[wm.EntityNode | None, str]:
    """Certain resolution only. Returns ``(node, how)``; ``how`` in
    ``{"alias", "entity_id", "exact", "ambiguous", "none"}``."""
    from services import working_memory as wmem

    phrase = str(phrase or "").strip()
    if not phrase:
        return None, "none"

    alias_target = wmem.find_alias(aliases or [], phrase)
    if alias_target:
        node = wm.by_id(entities, alias_target)
        if node:
            return node, "alias"

    if _ENTITY_ID_RE.match(phrase):
        node = wm.by_id(entities, phrase)
        if node:
            return node, "entity_id"

    matches = wm.find_exact(entities, phrase)
    if len(matches) == 1:
        return matches[0], "exact"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "none"


def compile_reflex(
    ctx: TurnContext,
    *,
    entities: list[wm.EntityNode],
    aliases: list[dict] | None = None,
) -> TurnContext:
    """Decide reflex vs agent for one short command."""
    text = ctx.user_text
    ctx.path = PATH_AGENT
    if not can_attempt_reflex(text):
        return ctx

    intent, expected, phrase = gc.parse_command(text)
    node, how = resolve_target(phrase, entities=entities, aliases=aliases)
    if node is None:
        ctx.confidence = 0.3 if how == "ambiguous" else 0.0
        return ctx

    domain = node.domain
    service = _SERVICE_TABLE.get(domain, {}).get(intent, "")
    if not service:
        # Verb doesn't apply to this entity ("aprinde yala") — let the agent explain.
        return ctx

    hyp = Hypothesis(
        intent=intent,
        score=0.99 if how in {"alias", "entity_id"} else 0.95,
        targets=[node.entity_id],
        area=node.area,
        service=service,
        domain=domain,
        reason=f"resolved={how}",
        expected_state=expected_state_for(domain, intent, expected),
    )
    ctx.hypotheses = [hyp]
    ctx.confidence = hyp.score
    ctx.goal = gc.goal_from_hypothesis(hyp, text)
    if ctx.goal.needs_approval:
        # Locks go through the agent / approval flow, never a silent reflex.
        return ctx
    ctx.path = PATH_SHADOW if ctx.shadow else PATH_REFLEX
    return ctx


async def execute_reflex(
    ctx: TurnContext,
    *,
    entities: list[wm.EntityNode] | None = None,
    cfg: dict | None = None,
) -> dict:
    """Execute the reflex hypothesis via ha_call_service."""
    from services import homeassistant as ha
    from services import autonomy_policy as ap
    from services import plan_engine as pe

    hyp = ctx.hypotheses[0] if ctx.hypotheses else None
    if not hyp or not hyp.targets:
        return {"ok": False, "error": "no_targets"}

    domain, service, data = service_for_hypothesis(hyp)
    if not domain or not service:
        return {"ok": False, "error": "unmapped_service"}

    decision = ap.decide(
        tool="ha_call_service",
        domain=domain,
        service=service,
        entity_ids=hyp.targets,
        cfg=cfg,
        user_id=ctx.user_id,
    )
    if decision == "deny":
        return {"ok": False, "error": "policy_deny", "policy": decision}
    if decision == "ask":
        return {"ok": False, "error": "policy_ask", "policy": decision}

    entity_id = hyp.targets[0]
    payload: dict[str, Any] = {
        "domain": domain,
        "service": service,
        "entity_id": entity_id,
        "verify": True,
    }
    if data:
        payload["data"] = data

    ledger_id = await pe.record_mutation_snapshot(
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        entity_ids=hyp.targets,
        action={"domain": domain, "service": service, "targets": hyp.targets},
    )

    try:
        result = await ha.run_ha_tool("ha_call_service", payload, cfg=cfg)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "ledger_id": ledger_id}

    ok = isinstance(result, str) and result.startswith("OK:")
    verify = pe.verify_delta(result, hyp.expected_state, hyp.targets) if ok else {
        "ok": False, "detail": result,
    }
    return {
        "ok": ok and verify.get("ok", True),
        "message": confirmation_text(hyp, lang=ctx.lang, entities=entities),
        "tool_result": result,
        "verify": verify,
        "ledger_id": ledger_id,
        "targets": hyp.targets,
        "hypothesis": hyp.to_dict(),
    }
