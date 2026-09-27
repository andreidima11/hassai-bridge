"""Reflex Tier 0 — compile short HA commands without an LLM round-trip.

High-confidence unique targets → execute (or shadow-log).
Ambiguous 2–5 targets → clarification chips.
Miss / complex → fall through to the agent.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from services.cognitive_kernel import (
    PATH_AGENT,
    PATH_CLARIFY,
    PATH_REFLEX,
    PATH_SHADOW,
    Hypothesis,
    TurnContext,
    pick_dominant_hypothesis,
)
from services import goal_compiler as gc
from services import world_model as wm

log = logging.getLogger("hassai.action_compiler")

_SHORT_MAX = 140


def can_attempt_reflex(user_text: str) -> bool:
    text = " ".join(str(user_text or "").split())
    if not text or len(text) > _SHORT_MAX:
        return False
    from services import deepseek as ds
    from services import tool_awareness as taw

    if ds.looks_like_automation_edit(text):
        return False
    if taw.looks_like_explain_event(text):
        return False
    if gc.detect_correction(text):
        return True  # handled specially
    return bool(ds.looks_like_control(text) or gc._base_action(text)[0])


def service_for_hypothesis(hyp: Hypothesis) -> tuple[str, str, dict]:
    """Map hypothesis → (domain, service, data)."""
    targets = list(hyp.targets or [])
    if not targets:
        return "", "", {}
    domain = targets[0].split(".", 1)[0]
    service = hyp.service or ""
    data: dict[str, Any] = {}

    if hyp.intent == "set_temperature":
        return "climate", "set_temperature", data

    if domain == "cover":
        if hyp.intent in {"close", "turn_off"}:
            return "cover", "close_cover", {}
        if hyp.intent in {"open", "turn_on"}:
            return "cover", "open_cover", {}
    if domain == "lock":
        if hyp.intent in {"lock", "close"}:
            return "lock", "lock", {}
        if hyp.intent in {"unlock", "open"}:
            return "lock", "unlock", {}
    if domain == "media_player":
        if hyp.intent == "pause":
            return "media_player", "media_pause", {}
        if hyp.intent == "stop":
            return "media_player", "media_stop", {}
        if hyp.intent == "turn_off":
            return "media_player", "turn_off", {}
        if hyp.intent == "turn_on":
            return "media_player", "turn_on", {}
    if domain == "climate" and hyp.intent == "set_temperature":
        return "climate", "set_temperature", data
    if hyp.intent == "toggle":
        return domain, "toggle", {}
    if hyp.intent in {"turn_on", "open"}:
        return domain, "turn_on", {}
    if hyp.intent in {"turn_off", "close", "stop"}:
        return domain, "turn_off", {}
    if service:
        return domain, service, data
    return domain, "", {}


def extract_temperature(text: str) -> float | None:
    m = gc._SET_TEMP.search(text or "")
    if not m:
        return None
    for g in m.groups():
        if g:
            try:
                val = float(g)
                if 5 <= val <= 35:
                    return val
            except ValueError:
                continue
    return None


def clarification_chips(hypotheses: list[Hypothesis], *, lang: str = "en") -> list[dict]:
    """Build UI chips for ambiguous targets."""
    chips: list[dict] = []
    seen: set[str] = set()
    for hyp in hypotheses:
        for eid in hyp.targets[:4]:
            if eid in seen:
                continue
            seen.add(eid)
            short = eid.split(".", 1)[-1].replace("_", " ")
            if lang == "ro":
                label = f"{hyp.intent.replace('_', ' ')} — {short}"
                prompt = f"{hyp.intent} {eid}"
            else:
                label = f"{hyp.intent.replace('_', ' ')} — {short}"
                prompt = f"{hyp.intent} {eid}"
            # Prefer natural prompts with entity_id for reliable re-compile
            if hyp.intent == "turn_off":
                prompt = f"turn off {eid}" if lang != "ro" else f"stinge {eid}"
            elif hyp.intent == "turn_on":
                prompt = f"turn on {eid}" if lang != "ro" else f"aprinde {eid}"
            elif hyp.intent == "close":
                prompt = f"close {eid}" if lang != "ro" else f"închide {eid}"
            elif hyp.intent == "open":
                prompt = f"open {eid}" if lang != "ro" else f"deschide {eid}"
            chips.append({
                "id": f"clarify_{eid}",
                "label": label[:48],
                "prompt": prompt,
                "topic": "clarify",
                "entity_id": eid,
            })
            if len(chips) >= 5:
                return chips
    return chips


def confirmation_text(hyp: Hypothesis, *, lang: str = "en", entities: list[wm.EntityNode] | None = None) -> str:
    names: list[str] = []
    by_id = {n.entity_id: n for n in (entities or [])}
    for eid in hyp.targets[:4]:
        node = by_id.get(eid)
        names.append(node.name if node else eid.split(".", 1)[-1].replace("_", " "))
    target = ", ".join(names) if names else (hyp.area or "device")
    area_bit = f" din {hyp.area}" if hyp.area and lang == "ro" else (f" in {hyp.area}" if hyp.area else "")
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
            "stop": f"Am oprit {target}.",
            "set_temperature": f"Am setat temperatura pentru {target}.",
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
        "stop": f"Stopped {target}.",
        "set_temperature": f"Set temperature for {target}.",
    }
    return mapping.get(hyp.intent, f"Done: {target}.")


def resolve_direct_entity_id(text: str) -> str | None:
    """Chip prompts may contain a raw entity_id."""
    m = re.search(r"\b([a-z_]+\.[a-z0-9_]+)\b", text or "", re.I)
    if m:
        return m.group(1).lower()
    return None


def compile_reflex(
    ctx: TurnContext,
    *,
    entities: list[wm.EntityNode],
    aliases: list[dict] | None = None,
) -> TurnContext:
    """Fill TurnContext path / hypotheses / chips for reflex decision."""
    text = ctx.user_text
    if not can_attempt_reflex(text):
        ctx.path = PATH_AGENT
        ctx.confidence = 0.0
        return ctx

    known_areas = sorted({n.area for n in entities if n.area})
    # Direct entity_id in message (from clarification chip)
    direct = resolve_direct_entity_id(text)
    if direct and any(n.entity_id == direct for n in entities):
        intent, service, expected = gc._base_action(text)
        if not intent:
            intent, service, expected = "turn_off", "turn_off", "off"
        hyp = Hypothesis(
            intent=intent,
            score=0.99,
            targets=[direct],
            area=next((n.area for n in entities if n.entity_id == direct), ""),
            service=service,
            domain=direct.split(".", 1)[0],
            reason="direct_entity_id",
            expected_state=expected,
        )
        ctx.hypotheses = [hyp]
        ctx.confidence = hyp.score
        ctx.goal = gc.goal_from_hypothesis(hyp, text)
        ctx.path = PATH_SHADOW if ctx.shadow else PATH_REFLEX
        ctx.world_snippet = wm.snippet_for_query(entities, text, limit=6)
        return ctx

    hypotheses = gc.compile_hypotheses(
        text,
        entities=entities,
        working_memory=ctx.working_memory,
        aliases=aliases,
        known_areas=known_areas,
    )
    ctx.hypotheses = hypotheses
    if not hypotheses:
        ctx.path = PATH_AGENT
        return ctx

    top = hypotheses[0]
    if top.intent in {"chat", "complex", "correction"}:
        ctx.path = PATH_AGENT
        ctx.confidence = top.score
        ctx.goal = gc.goal_from_hypothesis(top, text)
        return ctx

    if top.intent == "status":
        # Status still benefits from agent phrasing; inject world snippet
        ctx.path = PATH_AGENT
        ctx.confidence = top.score
        ctx.goal = gc.goal_from_hypothesis(top, text)
        ctx.world_snippet = wm.snippet_for_query(entities, text, area=top.area, limit=8)
        return ctx

    dominant = pick_dominant_hypothesis(hypotheses)
    # Unique target with high score
    if dominant and len(dominant.targets) == 1:
        ctx.confidence = dominant.score
        ctx.goal = gc.goal_from_hypothesis(dominant, text)
        if ctx.goal.needs_approval and ctx.goal.risk_class == "high":
            ctx.path = PATH_AGENT  # locks go through agent/policy
            ctx.world_snippet = wm.snippet_for_query(entities, text, limit=6)
            return ctx
        ctx.path = PATH_SHADOW if ctx.shadow else PATH_REFLEX
        return ctx

    # Explicit "all in area"
    if dominant and len(dominant.targets) > 1 and gc._ALL.search(text):
        ctx.confidence = dominant.score
        ctx.goal = gc.goal_from_hypothesis(dominant, text)
        ctx.path = PATH_SHADOW if ctx.shadow else PATH_REFLEX
        return ctx

    # Ambiguous: collect targets across beam
    all_targets: list[str] = []
    for h in hypotheses:
        for t in h.targets:
            if t not in all_targets:
                all_targets.append(t)
    if 2 <= len(all_targets) <= 5:
        ctx.confidence = top.score
        ctx.goal = gc.goal_from_hypothesis(top, text)
        ctx.clarification_chips = clarification_chips(hypotheses, lang=ctx.lang)
        ctx.path = PATH_CLARIFY
        return ctx

    ctx.path = PATH_AGENT
    ctx.confidence = top.score
    ctx.goal = gc.goal_from_hypothesis(top, text)
    ctx.world_snippet = wm.snippet_for_query(entities, text, area=top.area, limit=10)
    return ctx


async def execute_reflex(
    ctx: TurnContext,
    *,
    entities: list[wm.EntityNode] | None = None,
    cfg: dict | None = None,
) -> dict:
    """Execute the dominant reflex hypothesis via ha_call_service."""
    from services import homeassistant as ha
    from services import autonomy_policy as ap
    from services import plan_engine as pe

    hyp = pick_dominant_hypothesis(ctx.hypotheses) or (ctx.hypotheses[0] if ctx.hypotheses else None)
    if not hyp or not hyp.targets:
        return {"ok": False, "error": "no_targets"}

    decision = ap.decide(
        tool="ha_call_service",
        domain=hyp.targets[0].split(".", 1)[0],
        service=hyp.service or hyp.intent,
        entity_ids=hyp.targets,
        cfg=cfg,
        user_id=ctx.user_id,
    )
    if decision == "deny":
        return {"ok": False, "error": "policy_deny", "policy": decision}
    if decision == "ask":
        return {"ok": False, "error": "policy_ask", "policy": decision}

    domain, service, data = service_for_hypothesis(hyp)
    if hyp.intent == "set_temperature":
        temp = extract_temperature(ctx.user_text)
        if temp is None:
            return {"ok": False, "error": "missing_temperature"}
        data = {"temperature": temp}
        domain, service = "climate", "set_temperature"
    if not domain or not service:
        return {"ok": False, "error": "unmapped_service"}

    entity_id = hyp.targets[0] if len(hyp.targets) == 1 else None
    payload = {
        "domain": domain,
        "service": service,
        "verify": True,
    }
    if entity_id:
        payload["entity_id"] = entity_id
    else:
        payload["data"] = {**data, "entity_id": hyp.targets}
    if data and entity_id:
        payload["data"] = data

    # Snapshot for undo
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
    text = confirmation_text(hyp, lang=ctx.lang, entities=entities)
    return {
        "ok": ok and verify.get("ok", True),
        "message": text,
        "tool_result": result,
        "verify": verify,
        "ledger_id": ledger_id,
        "targets": hyp.targets,
        "hypothesis": hyp.to_dict(),
    }
