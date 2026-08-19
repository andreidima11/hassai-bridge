import pytest

from services import deepseek as ds
from services import provider_capabilities as pc


def test_preset_capabilities_deepseek_only():
    caps = pc.preset_capabilities("deepseek")
    assert "thinking" in caps
    assert "kv_cache" in caps
    assert pc.preset_capabilities("openai") == {}
    assert pc.preset_capabilities("local") == {}


def test_kv_cache_helpers():
    provider = {"type": "deepseek"}
    assert pc.supports_kv_cache(provider) is True
    assert pc.kv_context_budget(provider) == 98000
    hit, miss = pc.cache_tokens_from_usage(
        provider,
        {"prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 50},
    )
    assert hit == 100
    assert miss == 50


def test_provider_chat_capabilities_uses_provider_default():
    provider = {"type": "deepseek", "thinking_mode": "high"}
    caps = pc.provider_chat_capabilities(provider)
    assert caps["thinking"]["default"] == "high"


def test_auto_thinking_simple_vs_planning():
    simple = ds.auto_thinking_decision("ce faci?")
    assert simple["enabled"] is False

    planning = ds.auto_thinking_decision("Hai sa planuim arhitectura unei aplicatii React")
    assert planning["enabled"] is True
    assert planning["effort"] == "high"

    complex_q = ds.auto_thinking_decision(
        "Design from scratch the complete architecture for a multi-tenant SaaS platform"
    )
    assert complex_q["enabled"] is True
    assert complex_q["effort"] == "max"


def test_resolve_thinking_respects_override():
    provider = {"type": "deepseek", "thinking_mode": "auto"}
    off = pc.resolve_thinking(provider, override="off", user_text="plan architecture")
    assert off["enabled"] is False

    high = pc.resolve_thinking(provider, override="high", user_text="ce faci")
    assert high["enabled"] is True
    assert high["effort"] == "high"


def test_resolve_thinking_non_deepseek_returns_none():
    assert pc.resolve_thinking({"type": "openai"}, user_text="plan") is None


def test_apply_thinking_payload():
    payload = {}
    ds.apply_thinking_payload(payload, {"enabled": True, "effort": "max"})
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"

    payload = {}
    ds.apply_thinking_payload(payload, {"enabled": False, "effort": None})
    assert payload["thinking"] == {"type": "disabled"}


def test_assistant_turn_preserves_reasoning():
    msg = {"role": "assistant", "content": "ok", "reasoning_content": "step 1"}
    out = pc.assistant_turn({"type": "deepseek"}, msg)
    assert out["reasoning_content"] == "step 1"

    plain = pc.assistant_turn({"type": "openai"}, msg)
    assert "reasoning_content" not in plain
