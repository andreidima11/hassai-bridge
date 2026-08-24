"""Automatic provider selection.

Picks which configured provider answers a given turn, per request, without ever
writing to ``config.json`` — Auto mode must not race the Settings UI or hammer
the disk on every message.

Design notes:

* Deterministic rules, not an LLM router. Asking a model which model to use
  costs a full round trip before every reply; the signals below are free.
* The task class comes from the existing thinking classifier
  (``deepseek.auto_thinking_decision``) so intent detection lives in one place.
* Sessions are sticky. Prompt-cache hit rates dwarf the peak/off-peak spread
  (30x versus 2x on DeepSeek), so hopping providers mid-conversation to chase a
  cheaper rate usually costs more than it saves.
* Prices only break ties, and only while fresh. Everything still routes when
  the price table is stale or absent.
"""

from __future__ import annotations

import logging
import time

from services import deepseek as ds
from services import pricing
from services import provider_capabilities as pc
from services import providers as pv

log = logging.getLogger("hassai.router")

ROLES = ("fast", "deep", "vision", "fallback")
PROFILES = ("cheap", "balanced", "quality")

DEFAULT_ROUTING: dict = {
    "mode": "manual",          # manual | auto
    "profile": "balanced",
    "sticky_session": True,
    "roles": {role: "" for role in ROLES},
}

# Circuit breaker: after this many consecutive failures a provider is skipped
# until the cooldown expires.
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN_SEC = 120.0

# How long a session keeps its provider without new activity.
STICKY_TTL_SEC = 30 * 60

_breaker: dict[str, dict] = {}
_sticky: dict[str, dict] = {}


# ── Health state ───────────────────────────────────

def record_failure(provider_id: str, *, now: float | None = None) -> None:
    pid = str(provider_id or "").strip()
    if not pid:
        return
    now = now if now is not None else time.time()
    state = _breaker.setdefault(pid, {"failures": 0, "open_until": 0.0})
    state["failures"] += 1
    if state["failures"] >= BREAKER_THRESHOLD:
        state["open_until"] = now + BREAKER_COOLDOWN_SEC
        log.warning(
            "Provider %s tripped the circuit breaker (%s failures), skipping for %ss",
            pid, state["failures"], int(BREAKER_COOLDOWN_SEC),
        )


def record_success(provider_id: str) -> None:
    pid = str(provider_id or "").strip()
    if pid in _breaker:
        _breaker.pop(pid, None)


def is_open(provider_id: str, *, now: float | None = None) -> bool:
    state = _breaker.get(str(provider_id or "").strip())
    if not state:
        return False
    now = now if now is not None else time.time()
    if state["open_until"] and now < state["open_until"]:
        return True
    if state["open_until"]:
        # Cooldown elapsed — let it back in on probation.
        _breaker.pop(str(provider_id), None)
    return False


def breaker_state() -> dict:
    return {pid: dict(state) for pid, state in _breaker.items()}


def reset_state() -> None:
    """Drop breaker and stickiness state (tests, and provider config changes)."""
    _breaker.clear()
    _sticky.clear()


def forget_session(session_id: str) -> None:
    _sticky.pop(str(session_id or ""), None)


# ── Request classification ─────────────────────────

def classify(user_text: str, *, has_images: bool = False, tools_active: bool = False) -> str:
    """Map a turn onto a routing class: vision | simple | control | deep."""
    if has_images:
        return "vision"
    decision = ds.auto_thinking_decision(user_text or "", tools_active=tools_active)
    reason = decision.get("reason") or ""
    if reason == "control":
        # The thinking classifier checks control verbs before planning ones, which
        # is right for thinking (both end up on high effort) but wrong here: words
        # like "automatizare" make "hai să planificăm automatizarea casei" look
        # like a light switch. Planning wording wins for routing.
        return "deep" if ds.looks_like_planning(user_text) else "control"
    if reason in ("complex", "planning", "tools", "long"):
        return "deep"
    return "simple"


_CLASS_ROLE = {"vision": "vision", "deep": "deep", "control": "fast", "simple": "fast"}


# ── Config ─────────────────────────────────────────

def routing_config(cfg: dict | None) -> dict:
    raw = (cfg or {}).get("routing")
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_ROUTING)
    out.update({k: v for k, v in raw.items() if k != "roles"})
    roles = dict(DEFAULT_ROUTING["roles"])
    incoming = raw.get("roles")
    if isinstance(incoming, dict):
        for role in ROLES:
            roles[role] = str(incoming.get(role) or "").strip()
    out["roles"] = roles
    mode = str(out.get("mode") or "manual").strip().lower()
    out["mode"] = mode if mode in ("manual", "auto") else "manual"
    profile = str(out.get("profile") or "balanced").strip().lower()
    out["profile"] = profile if profile in PROFILES else "balanced"
    out["sticky_session"] = out.get("sticky_session") is not False
    return out


def is_auto(cfg: dict | None) -> bool:
    return routing_config(cfg)["mode"] == "auto"


# ── Candidate filtering ────────────────────────────

def eligible(
    provider: dict | None,
    *,
    need_vision: bool = False,
    need_tools: bool = False,
    prompt_tokens: int = 0,
    exclude: set | list | None = None,
    now: float | None = None,
) -> bool:
    """Hard filters — a provider that fails any of these cannot serve the turn."""
    if not isinstance(provider, dict) or not provider.get("id"):
        return False
    if exclude and provider["id"] in exclude:
        return False
    if is_open(provider["id"], now=now):
        return False
    if need_vision and not pv.provider_supports_vision(provider):
        return False
    # Weak tool callers narrate fake actions instead of calling the tool.
    if need_tools and provider.get("supports_tools") is False:
        return False
    if prompt_tokens and pc.context_budget(provider) < prompt_tokens:
        return False
    return True


def _sort_key(provider: dict, cfg: dict | None, now: float | None):
    signal = pricing.price_signal(provider, cfg, now=now)
    # Unknown price sorts after known ones without overriding the tier.
    return (
        pricing.tier_rank(provider, cfg),
        signal if signal is not None else float("inf"),
        str(provider.get("name") or provider.get("id") or ""),
    )


def cheapest(candidates: list[dict], cfg: dict | None = None, *, now: float | None = None) -> dict | None:
    return min(candidates, key=lambda p: _sort_key(p, cfg, now), default=None)


def most_capable(candidates: list[dict], cfg: dict | None = None, *, now: float | None = None) -> dict | None:
    """Highest tier wins; cheapest breaks ties inside the same tier."""
    def key(provider: dict):
        tier, signal, name = _sort_key(provider, cfg, now)
        return (-tier, signal if signal != float("inf") else 0.0, name)

    return min(candidates, key=key, default=None)


def derive_roles(candidates: list[dict], cfg: dict | None = None, *, now: float | None = None) -> dict:
    """Sensible role assignment when the user has not configured one.

    Auto mode has to work the moment it is switched on, whatever mix of
    providers happens to be configured.
    """
    roles: dict[str, dict | None] = {role: None for role in ROLES}
    if not candidates:
        return roles
    roles["fast"] = cheapest(candidates, cfg, now=now)
    thinkers = [p for p in candidates if pc.supports_thinking(p)]
    roles["deep"] = most_capable(thinkers or candidates, cfg, now=now)
    vision = [p for p in candidates if pv.provider_supports_vision(p)]
    roles["vision"] = cheapest(vision, cfg, now=now) if vision else None
    return roles


def role_model(provider: dict | None, role: str) -> str:
    """Model this provider should use for a role, or "" to keep its default."""
    if not isinstance(provider, dict):
        return ""
    models = provider.get("role_models")
    if not isinstance(models, dict):
        return ""
    return str(models.get(role) or "").strip()


def with_role_model(provider: dict, role: str) -> dict:
    """Swap in the role's model so everything downstream sees one provider record.

    Returning a provider whose ``model`` is already correct keeps the choice out
    of the request plumbing: capabilities, pricing, usage stats and the outbound
    payload all read the same field they always did.
    """
    chosen = role_model(provider, role)
    if not chosen or chosen == provider.get("model"):
        return provider
    return {**provider, "model": chosen}


def _by_id(candidates: list[dict], provider_id: str) -> dict | None:
    pid = str(provider_id or "").strip()
    if not pid:
        return None
    for provider in candidates:
        if provider.get("id") == pid:
            return provider
    return None


# ── Resolution ─────────────────────────────────────

def resolve(
    cfg: dict,
    *,
    providers: list[dict] | None = None,
    active: dict | None = None,
    session_id: str = "",
    user_text: str = "",
    has_images: bool = False,
    tools_active: bool = False,
    prompt_tokens: int = 0,
    exclude: set | list | None = None,
    now: float | None = None,
) -> dict:
    """Choose the provider — and its model — for one turn.

    Returns ``{"provider", "model", "klass", "role", "reason", "auto"}``. Never
    raises and never returns None for ``provider`` when one is configured — a
    routing problem must not become a failed reply.
    """
    now = now if now is not None else time.time()
    active = active if isinstance(active, dict) else pv.get_active_provider()
    conf = routing_config(cfg)
    klass = classify(user_text, has_images=has_images, tools_active=tools_active)

    if conf["mode"] != "auto":
        return {
            "provider": active, "model": active.get("model", ""),
            "klass": klass, "role": "", "reason": "manual", "auto": False,
        }

    pool = providers if providers is not None else (cfg.get("providers") or [])
    pool = [p for p in pool if isinstance(p, dict) and p.get("id")]
    if not pool:
        return {**_decision(active, klass, "", "no_providers")}

    need_vision = klass == "vision"
    need_tools = tools_active and klass == "control"
    usable = [
        p
        for p in pool
        if eligible(
            p,
            need_vision=need_vision,
            need_tools=need_tools,
            prompt_tokens=prompt_tokens,
            exclude=exclude,
            now=now,
        )
    ]
    if not usable:
        # Nothing passes the filters (all unhealthy, none has vision, …).
        # Fall back to the manual choice and let the normal error path speak.
        return _decision(active, klass, "", "no_candidate")

    role = _CLASS_ROLE.get(klass, "fast")

    # Stickiness: keep the session on its provider (prompt cache), but pick this
    # turn's role — and therefore its model — fresh. Escalating to deep leaves
    # sticky so a stronger provider can win; short follow-ups must not stay on
    # the planning model when the user configured a cheap/fast one.
    if conf["sticky_session"] and session_id and not exclude:
        remembered = _sticky.get(session_id)
        if remembered and (now - remembered.get("ts", 0)) <= STICKY_TTL_SEC:
            held = _by_id(usable, remembered.get("provider_id", ""))
            escalating = klass == "deep" and remembered.get("role") != "deep"
            if held is not None and not escalating:
                _remember(session_id, held, role, now)
                return _decision(
                    with_role_model(held, role), klass, role, "sticky",
                )

    configured = _by_id(usable, conf["roles"].get(role, ""))
    if configured is not None:
        chosen, reason = configured, f"role:{role}"
    else:
        derived = derive_roles(usable, cfg, now=now).get(role)
        if derived is not None:
            chosen, reason = derived, f"auto:{role}"
        else:
            # No provider fits the role (e.g. deep with nothing capable) —
            # any healthy provider beats refusing to answer.
            chosen = cheapest(usable, cfg, now=now) or active
            reason = "auto:any"

    if session_id:
        _remember(session_id, chosen, role, now)
    return _decision(with_role_model(chosen, role), klass, role, reason)


def _decision(provider: dict, klass: str, role: str, reason: str) -> dict:
    return {
        "provider": provider,
        "model": (provider or {}).get("model", ""),
        "klass": klass,
        "role": role,
        "reason": reason,
        "auto": True,
    }


def failover(
    cfg: dict,
    *,
    tried: list | set,
    providers: list[dict] | None = None,
    session_id: str = "",
    user_text: str = "",
    has_images: bool = False,
    tools_active: bool = False,
    prompt_tokens: int = 0,
    now: float | None = None,
) -> dict | None:
    """Next healthy provider after one just failed, or None to surface the error.

    Only Auto mode fails over. When the user pinned a provider by hand, quietly
    answering from a different one would be a surprise, not a feature.
    """
    if not is_auto(cfg):
        return None
    excluded = set(tried or ())
    decision = resolve(
        cfg,
        providers=providers,
        session_id=session_id,
        user_text=user_text,
        has_images=has_images,
        tools_active=tools_active,
        prompt_tokens=prompt_tokens,
        exclude=excluded,
        now=now,
    )
    # Only a genuine pick counts. resolve() falls back to the active provider
    # when nothing is eligible, and re-running a provider that just failed (or
    # one the filters rejected) would turn failover into a retry loop.
    if decision.get("reason") in ("manual", "no_providers", "no_candidate"):
        return None
    chosen = decision.get("provider")
    if not isinstance(chosen, dict) or chosen.get("id") in excluded:
        return None
    return chosen


def _remember(session_id: str, provider: dict, role: str, now: float) -> None:
    if not session_id or not isinstance(provider, dict) or not provider.get("id"):
        return
    _sticky[session_id] = {"provider_id": provider["id"], "role": role, "ts": now}
    if len(_sticky) > 500:
        stale = [sid for sid, row in _sticky.items() if now - row.get("ts", 0) > STICKY_TTL_SEC]
        for sid in stale:
            _sticky.pop(sid, None)
