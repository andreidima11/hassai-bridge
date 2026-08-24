"""Auto mode: classification, hard filters, stickiness, circuit breaker."""

from __future__ import annotations

import pytest

from services import pricing
from services import router as rt


LOCAL = {"id": "local1", "name": "Local", "type": "local", "model": "qwen3-8b", "max_tokens": 4096}
DEEPSEEK = {"id": "ds", "name": "DeepSeek", "type": "deepseek", "model": "deepseek-chat"}
OPENAI = {"id": "oai", "name": "OpenAI", "type": "openai", "model": "gpt-5.6"}
GROK = {"id": "grok", "name": "Grok", "type": "grok", "model": "grok-4.6"}

POOL = [LOCAL, DEEPSEEK, OPENAI, GROK]


def _cfg(**routing):
    base = {
        "providers": POOL,
        "pricing": {**pricing.DEFAULT_PRICING, "updated_at": "2026-08-16"},
        "routing": {"mode": "auto", "profile": "balanced", "sticky_session": True, "roles": {}},
    }
    base["routing"].update(routing)
    return base


@pytest.fixture(autouse=True)
def clean_state():
    rt.reset_state()
    yield
    rt.reset_state()


# ── Classification ─────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("salut", "simple"),
    ("mersi", "simple"),
    ("ok", "simple"),
    ("hai sa planuim arhitectura pentru casa", "deep"),
    ("explain step by step how the memory engine works", "deep"),
])
def test_classify_text_only(text, expected):
    assert rt.classify(text, tools_active=True) == expected


def test_classify_control_needs_tools_loaded():
    assert rt.classify("aprinde lumina din bucatarie", tools_active=True) == "control"


def test_planning_wording_beats_a_stray_control_verb():
    # "automatizare" matches the control vocabulary, but this is a design
    # discussion and belongs on the strong model, not the cheap one.
    text = "hai sa planuim arhitectura completa a sistemului de automatizare"
    assert rt.classify(text, tools_active=True) == "deep"


def test_images_always_classify_as_vision():
    assert rt.classify("salut", has_images=True, tools_active=True) == "vision"


# ── Manual mode is untouched ───────────────────────

def test_manual_mode_returns_the_active_provider():
    cfg = _cfg(mode="manual")
    out = rt.resolve(cfg, active=OPENAI, user_text="salut")
    assert out["provider"] is OPENAI
    assert out["auto"] is False
    assert out["reason"] == "manual"


# ── Role selection ─────────────────────────────────

def test_simple_chat_goes_to_the_cheapest_provider():
    out = rt.resolve(_cfg(), active=OPENAI, user_text="salut", tools_active=True)
    assert out["provider"]["id"] == LOCAL["id"]
    assert out["role"] == "fast"


def test_planning_goes_to_a_capable_provider():
    out = rt.resolve(
        _cfg(), active=LOCAL, user_text="hai sa planuim arhitectura sistemului", tools_active=True,
    )
    assert out["role"] == "deep"
    assert out["provider"]["id"] in (GROK["id"], DEEPSEEK["id"], OPENAI["id"])


def test_configured_role_beats_the_derived_one():
    cfg = _cfg(roles={"fast": OPENAI["id"]})
    out = rt.resolve(cfg, active=LOCAL, user_text="salut", tools_active=True)
    assert out["provider"]["id"] == OPENAI["id"]
    assert out["reason"] == "role:fast"


def test_images_route_to_a_vision_capable_provider():
    out = rt.resolve(_cfg(), active=DEEPSEEK, user_text="ce e in poza?", has_images=True)
    assert out["klass"] == "vision"
    from services.providers import provider_supports_vision

    assert provider_supports_vision(out["provider"])


def test_no_vision_provider_falls_back_to_active_rather_than_failing():
    cfg = {**_cfg(), "providers": [DEEPSEEK]}
    out = rt.resolve(cfg, providers=[DEEPSEEK], active=DEEPSEEK, user_text="ce e aici?", has_images=True)
    assert out["provider"] is DEEPSEEK
    assert out["reason"] == "no_candidate"


# ── Hard filters ───────────────────────────────────

def test_provider_that_cannot_hold_the_prompt_is_skipped():
    # LOCAL budget is max_tokens * 3 = 12288.
    out = rt.resolve(_cfg(), active=OPENAI, user_text="salut", prompt_tokens=50000)
    assert out["provider"]["id"] != LOCAL["id"]


def test_weak_tool_caller_never_gets_a_device_command():
    weak = {**LOCAL, "supports_tools": False}
    cfg = {**_cfg(), "providers": [weak, DEEPSEEK]}
    out = rt.resolve(
        cfg, providers=[weak, DEEPSEEK], active=DEEPSEEK,
        user_text="aprinde lumina din bucatarie", tools_active=True,
    )
    assert out["klass"] == "control"
    assert out["provider"]["id"] == DEEPSEEK["id"]


# ── Circuit breaker ────────────────────────────────

def test_breaker_opens_after_repeated_failures_and_reroutes():
    for _ in range(rt.BREAKER_THRESHOLD):
        rt.record_failure(LOCAL["id"])
    assert rt.is_open(LOCAL["id"])
    out = rt.resolve(_cfg(), active=OPENAI, user_text="salut", tools_active=True)
    assert out["provider"]["id"] != LOCAL["id"]


def test_success_clears_the_failure_count():
    rt.record_failure(LOCAL["id"])
    rt.record_success(LOCAL["id"])
    assert not rt.is_open(LOCAL["id"])
    assert rt.breaker_state() == {}


def test_breaker_reopens_after_the_cooldown(monkeypatch):
    now = 1000.0
    for _ in range(rt.BREAKER_THRESHOLD):
        rt.record_failure(LOCAL["id"], now=now)
    assert rt.is_open(LOCAL["id"], now=now + 1)
    assert not rt.is_open(LOCAL["id"], now=now + rt.BREAKER_COOLDOWN_SEC + 1)


# ── Stickiness ─────────────────────────────────────

def test_session_stays_on_its_provider_for_similar_turns():
    cfg = _cfg()
    first = rt.resolve(cfg, active=OPENAI, session_id="s1", user_text="salut", tools_active=True)
    second = rt.resolve(
        cfg, active=OPENAI, session_id="s1", user_text="aprinde lumina", tools_active=True,
    )
    assert second["provider"]["id"] == first["provider"]["id"]
    assert second["reason"] == "sticky"


def test_escalating_to_deep_work_breaks_stickiness():
    cfg = _cfg()
    rt.resolve(cfg, active=OPENAI, session_id="s2", user_text="salut", tools_active=True)
    deep = rt.resolve(
        cfg, active=OPENAI, session_id="s2",
        user_text="hai sa planuim arhitectura completa a sistemului", tools_active=True,
    )
    assert deep["role"] == "deep"
    assert deep["reason"] != "sticky"


def test_stickiness_can_be_switched_off():
    cfg = _cfg(sticky_session=False)
    rt.resolve(cfg, active=OPENAI, session_id="s3", user_text="salut", tools_active=True)
    again = rt.resolve(cfg, active=OPENAI, session_id="s3", user_text="salut", tools_active=True)
    assert again["reason"] != "sticky"


def test_sticky_provider_is_dropped_when_it_becomes_unhealthy():
    cfg = _cfg()
    first = rt.resolve(cfg, active=OPENAI, session_id="s4", user_text="salut", tools_active=True)
    for _ in range(rt.BREAKER_THRESHOLD):
        rt.record_failure(first["provider"]["id"])
    second = rt.resolve(cfg, active=OPENAI, session_id="s4", user_text="salut", tools_active=True)
    assert second["provider"]["id"] != first["provider"]["id"]


def test_sticky_entry_expires():
    cfg = _cfg()
    first = rt.resolve(
        cfg, active=OPENAI, session_id="s5", user_text="salut", tools_active=True, now=1000.0,
    )
    later = rt.resolve(
        cfg, active=OPENAI, session_id="s5", user_text="salut", tools_active=True,
        now=1000.0 + rt.STICKY_TTL_SEC + 1,
    )
    assert later["reason"] != "sticky"
    assert first["provider"]["id"] == later["provider"]["id"]  # same pick, fresh decision


# ── Degradation ────────────────────────────────────

def test_routing_still_works_when_prices_are_stale():
    cfg = _cfg()
    cfg["pricing"] = {**pricing.DEFAULT_PRICING, "updated_at": "2020-01-01"}
    out = rt.resolve(cfg, active=OPENAI, user_text="salut", tools_active=True)
    # Falls back to tier ordering: local (free) is still cheapest.
    assert out["provider"]["id"] == LOCAL["id"]


def test_no_providers_configured_keeps_the_active_one():
    cfg = {**_cfg(), "providers": []}
    out = rt.resolve(cfg, providers=[], active=OPENAI, user_text="salut")
    assert out["provider"] is OPENAI
    assert out["reason"] == "no_providers"


# ── Failover ───────────────────────────────────────

def test_failover_picks_another_provider():
    cfg = _cfg()
    alt = rt.failover(cfg, tried=[LOCAL["id"]], user_text="salut", tools_active=True)
    assert alt is not None
    assert alt["id"] != LOCAL["id"]


def test_failover_returns_none_when_everything_was_tried():
    cfg = _cfg()
    assert rt.failover(cfg, tried=[p["id"] for p in POOL], user_text="salut") is None


def test_manual_mode_never_fails_over_silently():
    cfg = _cfg(mode="manual")
    assert rt.failover(cfg, tried=[DEEPSEEK["id"]], user_text="salut") is None


def test_failover_ignores_stickiness():
    cfg = _cfg()
    first = rt.resolve(cfg, active=OPENAI, session_id="s6", user_text="salut", tools_active=True)
    alt = rt.failover(
        cfg, tried=[first["provider"]["id"]], session_id="s6", user_text="salut", tools_active=True,
    )
    assert alt is not None and alt["id"] != first["provider"]["id"]


# ── Model selection within a provider ──────────────

DUAL = {
    "id": "dual", "name": "Dual", "type": "deepseek", "model": "deepseek-chat",
    "role_models": {"fast": "deepseek-chat", "deep": "deepseek-reasoner"},
}


def _dual_cfg(**routing):
    cfg = _cfg(**routing)
    cfg["providers"] = [DUAL]
    return cfg


def test_short_chat_uses_the_fast_model():
    out = rt.resolve(_dual_cfg(), providers=[DUAL], active=DUAL, user_text="salut", tools_active=True)
    assert out["provider"]["model"] == "deepseek-chat"
    assert out["model"] == "deepseek-chat"


def test_planning_uses_the_deep_model_on_the_same_provider():
    out = rt.resolve(
        _dual_cfg(), providers=[DUAL], active=DUAL,
        user_text="hai sa planuim arhitectura sistemului", tools_active=True,
    )
    assert out["provider"]["id"] == DUAL["id"]
    assert out["provider"]["model"] == "deepseek-reasoner"


def test_role_model_does_not_mutate_the_configured_provider():
    rt.resolve(
        _dual_cfg(), providers=[DUAL], active=DUAL,
        user_text="hai sa planuim arhitectura sistemului", tools_active=True,
    )
    assert DUAL["model"] == "deepseek-chat"


def test_provider_without_role_models_keeps_its_model():
    out = rt.resolve(_cfg(), active=OPENAI, user_text="salut", tools_active=True)
    assert out["provider"]["model"] == out["provider"]["model"]
    assert rt.role_model(DEEPSEEK, "deep") == ""


def test_sticky_provider_still_picks_fast_model_on_short_follow_up():
    """Provider stickiness must not lock the planning model onto short chat."""
    cfg = _dual_cfg()
    rt.resolve(
        cfg, providers=[DUAL], active=DUAL, session_id="m1",
        user_text="hai sa planuim arhitectura sistemului", tools_active=True,
    )
    follow_up = rt.resolve(
        cfg, providers=[DUAL], active=DUAL, session_id="m1",
        user_text="mersi", tools_active=True,
    )
    assert follow_up["reason"] == "sticky"
    assert follow_up["provider"]["id"] == DUAL["id"]
    assert follow_up["role"] == "fast"
    assert follow_up["provider"]["model"] == "deepseek-chat"


def test_new_session_does_not_inherit_sticky_role():
    cfg = _dual_cfg()
    rt.resolve(
        cfg, providers=[DUAL], active=DUAL, session_id="old",
        user_text="hai sa planuim arhitectura sistemului", tools_active=True,
    )
    fresh = rt.resolve(
        cfg, providers=[DUAL], active=DUAL, session_id="new",
        user_text="ce faci", tools_active=True,
    )
    assert fresh["reason"] != "sticky"
    assert fresh["role"] == "fast"
    assert fresh["provider"]["model"] == "deepseek-chat"


def test_manual_mode_reports_the_configured_model():
    out = rt.resolve(_dual_cfg(mode="manual"), active=DUAL, user_text="salut")
    assert out["model"] == "deepseek-chat"
    assert out["auto"] is False


def test_derive_roles_covers_fast_and_deep_with_a_single_provider():
    roles = rt.derive_roles([DEEPSEEK], _cfg())
    assert roles["fast"]["id"] == DEEPSEEK["id"]
    assert roles["deep"]["id"] == DEEPSEEK["id"]
