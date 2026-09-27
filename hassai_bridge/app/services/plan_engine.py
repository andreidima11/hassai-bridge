"""Plan DAG + State Delta Verifier + mutation ledger / undo."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("hassai.plan_engine")

PHASE_READ = "read"
PHASE_WRITE = "write"
PHASE_VERIFY = "verify"


@dataclass
class PlanNode:
    id: str
    tool: str
    args: dict = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    phase: str = PHASE_READ
    expected_delta: dict = field(default_factory=dict)
    timeout_sec: float = 30.0
    on_fail: str = "abort"  # abort | retry | ask

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plan:
    plan_id: str
    nodes: list[PlanNode] = field(default_factory=list)
    goal: str = ""

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "nodes": [n.to_dict() for n in self.nodes],
        }


def new_plan_id() -> str:
    return f"plan_{uuid.uuid4().hex[:12]}"


def build_control_plan(
    *,
    entity_ids: list[str],
    domain: str,
    service: str,
    expected_state: str = "",
    data: dict | None = None,
) -> Plan:
    """Simple read→write→verify DAG for a control action."""
    plan = Plan(plan_id=new_plan_id(), goal=f"{domain}.{service}")
    read_ids = []
    for i, eid in enumerate(entity_ids[:8]):
        nid = f"read_{i}"
        read_ids.append(nid)
        plan.nodes.append(PlanNode(
            id=nid,
            tool="ha_get_state",
            args={"entity_id": eid},
            phase=PHASE_READ,
        ))
    write_id = "write_0"
    write_args: dict[str, Any] = {"domain": domain, "service": service, "verify": False}
    if len(entity_ids) == 1:
        write_args["entity_id"] = entity_ids[0]
        if data:
            write_args["data"] = data
    else:
        write_args["data"] = {**(data or {}), "entity_id": entity_ids}
    plan.nodes.append(PlanNode(
        id=write_id,
        tool="ha_call_service",
        args=write_args,
        deps=list(read_ids),
        phase=PHASE_WRITE,
        expected_delta={"state": expected_state} if expected_state else {},
        on_fail="ask",
    ))
    if expected_state:
        for i, eid in enumerate(entity_ids[:8]):
            plan.nodes.append(PlanNode(
                id=f"verify_{i}",
                tool="ha_get_state",
                args={"entity_id": eid},
                deps=[write_id],
                phase=PHASE_VERIFY,
                expected_delta={"entity_id": eid, "state": expected_state},
            ))
    return plan


def ready_nodes(plan: Plan, done: set[str]) -> list[PlanNode]:
    out = []
    for n in plan.nodes:
        if n.id in done:
            continue
        if all(d in done for d in n.deps):
            out.append(n)
    return out


async def execute_plan(
    plan: Plan,
    *,
    invoke: Callable[[str, dict], Awaitable[str]],
    parallel_reads: bool = True,
) -> dict:
    """Execute a DAG: parallel reads, ordered writes."""
    done: set[str] = set()
    results: dict[str, str] = {}
    errors: list[str] = []

    while len(done) < len(plan.nodes):
        ready = ready_nodes(plan, done)
        if not ready:
            errors.append("deadlock_or_missing_deps")
            break
        # Prefer completing an entire read wave in parallel
        wave = ready
        if parallel_reads and all(n.phase == PHASE_READ for n in ready):
            import asyncio

            async def _one(n: PlanNode) -> tuple[str, str]:
                try:
                    return n.id, await invoke(n.tool, n.args)
                except Exception as exc:
                    return n.id, f"Error: {exc}"

            pairs = await asyncio.gather(*[_one(n) for n in wave])
            for nid, content in pairs:
                results[nid] = content
                done.add(nid)
                if str(content).startswith("Error"):
                    errors.append(f"{nid}: {content}")
            continue

        # Sequential for writes / mixed
        node = sorted(wave, key=lambda n: (0 if n.phase == PHASE_READ else 1, n.id))[0]
        try:
            content = await invoke(node.tool, node.args)
        except Exception as exc:
            content = f"Error: {exc}"
            errors.append(f"{node.id}: {content}")
            if node.on_fail == "abort":
                results[node.id] = content
                done.add(node.id)
                break
        results[node.id] = content
        done.add(node.id)
        if str(content).startswith("Error") and node.phase == PHASE_WRITE:
            break

    return {
        "ok": not errors,
        "plan_id": plan.plan_id,
        "results": results,
        "errors": errors,
        "done": sorted(done),
    }


def verify_delta(tool_result: str, expected_state: str, entity_ids: list[str]) -> dict:
    """Parse ha_call_service verify block / state text for expected state."""
    text = str(tool_result or "")
    if not expected_state:
        return {"ok": True, "detail": "no_expected_state"}
    expected = expected_state.lower().strip()
    missing: list[str] = []
    for eid in entity_ids:
        # Look for entity block mentioning state=
        idx = text.find(eid)
        if idx < 0:
            # OK line without per-entity verify still counts soft-ok if OK:
            if text.startswith("OK:") and "verify:" not in text:
                continue
            missing.append(eid)
            continue
        window = text[idx : idx + 400].lower()
        if f"state: {expected}" in window or f"state={expected}" in window:
            continue
        # Some formatters use "state: on"
        if f"\nstate: {expected}" in window or f"|{expected}|" in window:
            continue
        # If verify section exists but state differs
        if "state:" in window or "state=" in window:
            missing.append(eid)
    return {
        "ok": not missing,
        "expected": expected,
        "failed_entities": missing,
        "detail": "ok" if not missing else f"state_mismatch:{','.join(missing)}",
    }


async def record_mutation_snapshot(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    entity_ids: list[str],
    action: dict,
) -> str | None:
    """Capture pre-mutation states into mutation_ledger."""
    from core import database as db
    from services import homeassistant as ha

    ledger_id = f"mut_{uuid.uuid4().hex[:12]}"
    snapshots: dict[str, Any] = {}
    if ha.is_available():
        for eid in entity_ids[:12]:
            try:
                state = await ha._core("GET", f"/states/{eid}")
                if isinstance(state, dict):
                    snapshots[eid] = {
                        "state": state.get("state"),
                        "attributes": {
                            k: state.get("attributes", {}).get(k)
                            for k in ("brightness", "temperature", "current_position", "volume_level")
                            if k in (state.get("attributes") or {})
                        },
                    }
            except Exception:
                snapshots[eid] = {"state": None}
    try:
        db.add_mutation_ledger(
            ledger_id=ledger_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            action=action,
            snapshots=snapshots,
        )
    except Exception:
        log.debug("mutation ledger write failed", exc_info=True)
        return None
    return ledger_id


async def undo_ledger(
    ledger_id: str,
    *,
    cfg: dict | None = None,
    user_id: str | None = None,
) -> dict:
    """Best-effort undo: restore previous states via domain.turn_on/off / set.

    Ownership: when user_id is provided, the ledger must belong to that user.
    Idempotent: a second undo on an already-undone ledger returns ok without
    re-calling HA.
    """
    from core import database as db
    from services import homeassistant as ha

    row = db.get_mutation_ledger(ledger_id)
    if not row:
        return {"ok": False, "error": "ledger_not_found"}
    if user_id is not None and str(row.get("user_id") or "") != str(user_id):
        return {"ok": False, "error": "forbidden"}
    if row.get("undone_at"):
        return {"ok": True, "restored": [], "errors": [], "already_undone": True}
    snapshots = row.get("snapshots") or {}
    restored: list[str] = []
    errors: list[str] = []
    for eid, snap in snapshots.items():
        prev = str((snap or {}).get("state") or "").lower()
        domain = eid.split(".", 1)[0]
        try:
            if domain in {"light", "switch", "fan", "input_boolean", "media_player"}:
                service = "turn_on" if prev == "on" else "turn_off"
                await ha.run_ha_tool(
                    "ha_call_service",
                    {"domain": domain, "service": service, "entity_id": eid, "verify": False},
                    cfg=cfg,
                )
                restored.append(eid)
            elif domain == "cover" and prev in {"open", "closed", "close"}:
                service = "open_cover" if prev == "open" else "close_cover"
                await ha.run_ha_tool(
                    "ha_call_service",
                    {"domain": domain, "service": service, "entity_id": eid, "verify": False},
                    cfg=cfg,
                )
                restored.append(eid)
            elif domain == "lock" and prev in {"locked", "unlocked"}:
                service = "lock" if prev == "locked" else "unlock"
                await ha.run_ha_tool(
                    "ha_call_service",
                    {"domain": domain, "service": service, "entity_id": eid, "verify": False},
                    cfg=cfg,
                )
                restored.append(eid)
            else:
                errors.append(f"{eid}: unsupported undo domain/state")
        except Exception as exc:
            errors.append(f"{eid}: {exc}")
    db.mark_mutation_undone(ledger_id)
    return {"ok": not errors, "restored": restored, "errors": errors}
