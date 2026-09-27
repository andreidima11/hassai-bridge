"""Evidence-based proactive suggestions (bounded autonomy).

Observes HA deviations / habit misses and proposes chips — executes only when
autonomy_policy explicitly allows proactive mutations.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core import database as db
from services import autonomy_policy as ap
from services import world_model as wm

log = logging.getLogger("hassai.opportunity")

# entity_id → recent state samples {ts, state}
_RECENT: dict[str, list[dict]] = {}
_OPEN_STUCK_SEC = 30 * 60
_UNAVAILABLE_SEC = 15 * 60


def observe_state(entity_id: str, new_state: str, *, old_state: str = "") -> None:
    eid = str(entity_id or "").strip()
    if not eid:
        return
    bucket = _RECENT.setdefault(eid, [])
    bucket.append({"ts": time.time(), "state": str(new_state or ""), "old": str(old_state or "")})
    if len(bucket) > 40:
        del bucket[:-40]
    # Keep world model fresh
    try:
        wm.apply_state_event(eid, new_state)
    except Exception:
        pass


def _evidence_open_too_long(eid: str, state: str) -> dict | None:
    st = state.lower()
    if st not in {"open", "on", "unlocked"}:
        return None
    domain = eid.split(".", 1)[0]
    if domain not in {"cover", "lock", "binary_sensor"} and "door" not in eid and "garaj" not in eid and "poart" not in eid:
        # only door-like / cover / lock
        if domain not in {"cover", "lock"}:
            return None
    hist = _RECENT.get(eid) or []
    if not hist:
        return None
    # Find when it entered this state
    entered = hist[-1]["ts"]
    for sample in reversed(hist[:-1]):
        if str(sample.get("state") or "").lower() == st:
            entered = sample["ts"]
        else:
            break
    age = time.time() - entered
    if age < _OPEN_STUCK_SEC:
        return None
    return {
        "kind": "stuck_open",
        "entity_id": eid,
        "state": st,
        "age_sec": int(age),
        "evidence": ["state_duration", f"age>={_OPEN_STUCK_SEC}"],
        "risk": "medium",
    }


def _evidence_unavailable(eid: str, state: str) -> dict | None:
    if state.lower() not in {"unavailable", "unknown"}:
        return None
    hist = _RECENT.get(eid) or []
    entered = hist[-1]["ts"] if hist else time.time()
    for sample in reversed(hist[:-1]):
        if str(sample.get("state") or "").lower() in {"unavailable", "unknown"}:
            entered = sample["ts"]
        else:
            break
    if time.time() - entered < _UNAVAILABLE_SEC:
        return None
    return {
        "kind": "device_degraded",
        "entity_id": eid,
        "state": state.lower(),
        "age_sec": int(time.time() - entered),
        "evidence": ["unavailable_duration"],
        "risk": "low",
    }


def evaluate_entity(entity_id: str, state: str) -> list[dict]:
    out = []
    for fn in (_evidence_open_too_long, _evidence_unavailable):
        hit = fn(entity_id, state)
        if hit:
            out.append(hit)
    return out


def suggestion_chip(opportunity: dict, *, lang: str = "en") -> dict:
    eid = opportunity.get("entity_id") or ""
    kind = opportunity.get("kind")
    short = eid.split(".")[-1].replace("_", " ") if eid else "device"
    if kind == "stuck_open":
        if lang == "ro":
            label = f"Închide {short}?"
            prompt = f"închide {eid}"
        else:
            label = f"Close {short}?"
            prompt = f"close {eid}"
    elif kind == "device_degraded":
        if lang == "ro":
            label = f"Verifică {short}"
            prompt = f"de ce e unavailable {eid}"
        else:
            label = f"Check {short}"
            prompt = f"why is {eid} unavailable"
    else:
        label = short
        prompt = eid
    return {
        "id": f"opp_{kind}_{eid}",
        "label": label[:48],
        "prompt": prompt,
        "topic": "opportunity",
        "entity_id": eid,
        "kind": kind,
    }


def process_opportunities(
    *,
    user_id: str,
    lang: str = "en",
    cfg: dict | None = None,
    limit: int = 3,
) -> list[dict]:
    """Scan recent observations, persist suggestions, return chips."""
    pol = (cfg or {}).get("autonomy_policy") if isinstance((cfg or {}).get("autonomy_policy"), dict) else {}
    if pol.get("proactive_suggestions", True) is False:
        return []

    chips: list[dict] = []
    seen: set[str] = set()
    for eid, samples in list(_RECENT.items()):
        if not samples:
            continue
        state = str(samples[-1].get("state") or "")
        for opp in evaluate_entity(eid, state):
            key = f"{opp['kind']}:{eid}"
            if key in seen:
                continue
            # Suppress if user dismissed recently
            if db.is_opportunity_suppressed(user_id, key):
                continue
            seen.add(key)
            chip = suggestion_chip(opp, lang=lang)
            try:
                db.add_opportunity(
                    user_id=user_id,
                    key=key,
                    kind=str(opp["kind"]),
                    payload=opp,
                )
            except Exception:
                log.debug("opportunity persist failed", exc_info=True)
            chips.append(chip)
            if len(chips) >= limit:
                return chips
    return chips


def feedback(user_id: str, key: str, *, action: str) -> None:
    """action: accept | dismiss | mute."""
    if action in {"dismiss", "mute"}:
        db.suppress_opportunity(user_id, key, mute=(action == "mute"))
    elif action == "accept":
        db.mark_opportunity_accepted(user_id, key)


async def maybe_auto_act(opportunity: dict, *, user_id: str, cfg: dict | None = None) -> dict:
    """Execute only when policy allows proactive mutations."""
    kind = opportunity.get("kind")
    eid = str(opportunity.get("entity_id") or "")
    if kind != "stuck_open" or not eid:
        return {"ok": False, "error": "not_auto"}
    domain = eid.split(".", 1)[0]
    service = "close_cover" if domain == "cover" else "turn_off" if domain in {"light", "switch"} else ""
    if domain == "lock":
        service = "lock"
    if not service:
        return {"ok": False, "error": "no_service"}
    decision = ap.decide(
        tool="ha_call_service",
        domain=domain,
        service=service,
        entity_ids=[eid],
        cfg=cfg,
        user_id=user_id,
        proactive=True,
    )
    if decision != "allow":
        return {"ok": False, "error": f"policy_{decision}", "suggest_only": True}
    from services import homeassistant as ha
    out = await ha.run_ha_tool(
        "ha_call_service",
        {"domain": domain, "service": service, "entity_id": eid, "verify": True},
        cfg=cfg,
    )
    ap.record_proactive_hit(user_id)
    return {"ok": isinstance(out, str) and out.startswith("OK:"), "result": out}
