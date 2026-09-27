"""Cognitive OS scorecard — latency, success, clarifications, cost."""

from __future__ import annotations

import logging
import time
from typing import Any

from core import database as db
from services.cognitive_kernel import TurnContext, elapsed_ms

log = logging.getLogger("hassai.cognitive_metrics")


def record_turn(ctx: TurnContext, *, outcome: dict | None = None) -> None:
    """Persist one cognitive turn for scorecards / evals."""
    outcome = outcome or {}
    try:
        db.add_cognitive_trace(
            turn_id=ctx.turn_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            path=ctx.path,
            confidence=ctx.confidence,
            route_klass=ctx.route_klass,
            user_text=ctx.user_text,
            goal=(ctx.goal.to_dict() if ctx.goal else {}),
            hypotheses=[h.to_dict() for h in ctx.hypotheses],
            outcome=outcome,
            metrics={
                **ctx.metrics,
                "elapsed_ms": elapsed_ms(ctx),
                "time_to_first_action_ms": ctx.metrics.get("t_action_ms"),
                "shadow": ctx.shadow,
                "policy": ctx.policy_decision,
                "clarify_chips": len(ctx.clarification_chips),
            },
        )
    except Exception:
        log.debug("cognitive trace write failed", exc_info=True)


def scorecard(*, user_id: str = "", since_hours: float = 24.0) -> dict[str, Any]:
    """Aggregate recent cognitive traces into a scorecard."""
    try:
        rows = db.list_cognitive_traces(user_id=user_id, since_hours=since_hours, limit=500)
    except Exception:
        rows = []
    if not rows:
        return {
            "turns": 0,
            "since_hours": since_hours,
            "paths": {},
            "success_rate": None,
            "avg_elapsed_ms": None,
            "clarify_rate": None,
            "shadow_turns": 0,
        }

    paths: dict[str, int] = {}
    successes = 0
    known = 0
    elapsed: list[int] = []
    clarify = 0
    shadow = 0
    verify_fail = 0
    undo = 0

    for row in rows:
        path = str(row.get("path") or "agent")
        paths[path] = paths.get(path, 0) + 1
        metrics = row.get("metrics") or {}
        outcome = row.get("outcome") or {}
        if metrics.get("shadow") or row.get("path") == "shadow":
            shadow += 1
        if int(metrics.get("clarify_chips") or 0) > 0 or path == "clarify":
            clarify += 1
        ms = metrics.get("elapsed_ms")
        if ms is not None:
            try:
                elapsed.append(int(ms))
            except (TypeError, ValueError):
                pass
        if "ok" in outcome:
            known += 1
            if outcome.get("ok"):
                successes += 1
        if (outcome.get("verify") or {}).get("ok") is False:
            verify_fail += 1
        if outcome.get("undone"):
            undo += 1

    return {
        "turns": len(rows),
        "since_hours": since_hours,
        "paths": paths,
        "success_rate": (successes / known) if known else None,
        "success_known": known,
        "avg_elapsed_ms": int(sum(elapsed) / len(elapsed)) if elapsed else None,
        "p50_elapsed_ms": sorted(elapsed)[len(elapsed) // 2] if elapsed else None,
        "clarify_rate": clarify / len(rows),
        "shadow_turns": shadow,
        "verify_failures": verify_fail,
        "undos": undo,
    }


def eval_fixture_result(
    *,
    utterance: str,
    expected_path: str,
    expected_targets: list[str] | None = None,
    ctx: TurnContext,
) -> dict:
    """Compare a compiled TurnContext against an eval fixture expectation."""
    targets = []
    if ctx.hypotheses:
        targets = list(ctx.hypotheses[0].targets or [])
    ok_path = ctx.path == expected_path or (
        expected_path == "reflex" and ctx.path in {"reflex", "shadow"}
    )
    ok_targets = True
    if expected_targets:
        ok_targets = set(expected_targets).issubset(set(targets)) or set(targets) == set(expected_targets)
    return {
        "utterance": utterance,
        "ok": ok_path and ok_targets,
        "path": ctx.path,
        "expected_path": expected_path,
        "targets": targets,
        "expected_targets": expected_targets or [],
        "confidence": ctx.confidence,
    }
