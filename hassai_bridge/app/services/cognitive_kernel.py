"""Cognitive Kernel — unified turn decision for HASSAI.

Builds a structured TurnContext before the main LLM path. A reflex executes
only when the target is certain; otherwise the agent continues with richer
context (house index, recent actions, learned aliases).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("hassai.cognitive")

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

PATH_REFLEX = "reflex"
PATH_AGENT = "agent"
PATH_SKILL = "skill"
PATH_SHADOW = "shadow"

# Recent actions older than this are not worth mentioning to the model.
RECENT_ACTION_TTL_S = 15 * 60


@dataclass
class Hypothesis:
    """The reflex's single interpretation of a command."""

    intent: str
    score: float
    targets: list[str] = field(default_factory=list)
    area: str = ""
    service: str = ""
    domain: str = ""
    reason: str = ""
    expected_state: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GoalContract:
    """What success looks like for this turn."""

    goal: str
    success_criteria: str = ""
    risk_class: str = RISK_LOW
    reversible: bool = True
    needs_approval: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TurnContext:
    """Structured cognition for one chat turn."""

    turn_id: str
    user_id: str
    session_id: str
    user_text: str
    lang: str = "en"
    route_klass: str = "simple"
    path: str = PATH_AGENT
    confidence: float = 0.0
    hypotheses: list[Hypothesis] = field(default_factory=list)
    goal: GoalContract | None = None
    working_memory: dict = field(default_factory=dict)
    recent_actions_text: str = ""
    world_snippet: str = ""
    aliases_used: list[dict] = field(default_factory=list)
    plan: dict | None = None
    policy_decision: str = "allow"
    shadow: bool = False
    metrics: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "user_text": self.user_text,
            "lang": self.lang,
            "route_klass": self.route_klass,
            "path": self.path,
            "confidence": self.confidence,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "goal": self.goal.to_dict() if self.goal else None,
            "working_memory": self.working_memory,
            "recent_actions_text": self.recent_actions_text,
            "world_snippet": self.world_snippet,
            "aliases_used": self.aliases_used,
            "plan": self.plan,
            "policy_decision": self.policy_decision,
            "shadow": self.shadow,
            "metrics": self.metrics,
            "started_at": self.started_at,
        }


def new_turn_id() -> str:
    return f"cog_{uuid.uuid4().hex[:16]}"


def cognitive_enabled(cfg: dict | None) -> bool:
    perf = (cfg or {}).get("performance") or {}
    return perf.get("cognitive_os", True) is not False


def reflex_enabled(cfg: dict | None) -> bool:
    if not cognitive_enabled(cfg):
        return False
    perf = (cfg or {}).get("performance") or {}
    return perf.get("action_compiler", True) is not False


def shadow_mode(cfg: dict | None) -> bool:
    """When true, reflex/skill decisions are logged but not executed."""
    perf = (cfg or {}).get("performance") or {}
    return bool(perf.get("cognitive_shadow", False))


def build_turn_context(
    *,
    user_text: str,
    user_id: str = "",
    session_id: str = "",
    lang: str = "en",
    route_klass: str = "simple",
    cfg: dict | None = None,
) -> TurnContext:
    """Create a TurnContext shell; callers fill hypotheses / goal / path."""
    return TurnContext(
        turn_id=new_turn_id(),
        user_id=str(user_id or ""),
        session_id=str(session_id or ""),
        user_text=str(user_text or "").strip(),
        lang="ro" if str(lang or "").lower().startswith("ro") else "en",
        route_klass=str(route_klass or "simple"),
        shadow=shadow_mode(cfg),
        metrics={"t0": time.time()},
    )


def late_context_block(ctx: TurnContext) -> str:
    """Compact block injected on the last user turn (KV-cache friendly).

    Recent actions are *described*, never applied: the model decides whether
    "and that one too" refers to them. The house index lets it resolve names.
    """
    parts: list[str] = []
    if ctx.recent_actions_text:
        parts.append("[Recent actions]\n" + ctx.recent_actions_text.strip())
    if ctx.aliases_used:
        lines = [
            f"- {a.get('surface')} → {a.get('resolves_to')}"
            for a in ctx.aliases_used[:8]
            if a.get("surface") and a.get("resolves_to")
        ]
        if lines:
            parts.append("[Learned names]\n" + "\n".join(lines))
    if ctx.world_snippet:
        parts.append("[House index]\n" + ctx.world_snippet.strip())
    if ctx.goal and ctx.goal.goal:
        parts.append(
            f"[Goal] {ctx.goal.goal}"
            + (f" | success: {ctx.goal.success_criteria}" if ctx.goal.success_criteria else "")
        )
    return "\n\n".join(parts)


def mark_metric(ctx: TurnContext, key: str, value: Any = None) -> None:
    if value is None:
        value = time.time()
    ctx.metrics[key] = value


def elapsed_ms(ctx: TurnContext, start_key: str = "t0", end_key: str | None = None) -> int:
    start = float(ctx.metrics.get(start_key) or ctx.started_at)
    end = float(ctx.metrics.get(end_key) if end_key else time.time())
    return max(0, int((end - start) * 1000))
