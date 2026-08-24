import pytest

from services import deepseek as ds
from services import provider_capabilities as pc


def test_preset_capabilities_deepseek_only():
    caps = pc.preset_capabilities("deepseek")
    assert "thinking" in caps
    assert "kv_cache" in caps
    grok_caps = pc.preset_capabilities("grok")
    assert "thinking" in grok_caps
    assert "kv_cache" in grok_caps
    openai_caps = pc.preset_capabilities("openai")
    assert "kv_cache" in openai_caps
    assert "thinking" not in openai_caps
    assert pc.preset_capabilities("local") == {"kv_cache": {"context_budget": 6144}}


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


@pytest.mark.parametrize("text", [
    "turn on the lights",
    "turn off living room light",
    "aprinde lumina",
    "stinge becul din bucătărie",
    "setează termostatul la 22",
    "deschide ușa",
    "dă ultimul snap",
    "ce e pe cameră",
    "ce se vede pe frigate",
    "list entities in kitchen",
    "restart home assistant",
    "ține minte că am o pisică",
])
def test_auto_thinking_tags_control_without_enabling(text):
    """HA intents stay tagged for routing, but Auto does not burn CoT on them."""
    decision = ds.auto_thinking_decision(text, tools_active=True)
    assert decision["enabled"] is False
    assert decision["effort"] is None
    assert decision["reason"] == "control"


def test_auto_thinking_control_stays_off_without_tools():
    # No tools loaded → don't even tag as control (falls through to simple/off).
    decision = ds.auto_thinking_decision("aprinde lumina", tools_active=False)
    assert decision["enabled"] is False
    assert decision["reason"] != "control"


def test_auto_thinking_greetings_stay_off_even_with_tools():
    for text in ("ok", "da", "mulțumesc", "ce faci?", "hello"):
        decision = ds.auto_thinking_decision(text, tools_active=True)
        assert decision["enabled"] is False, text


def test_resolve_thinking_auto_leaves_control_off_on_deepseek():
    provider = {"type": "deepseek", "thinking_mode": "auto"}
    out = pc.resolve_thinking(
        provider, override="auto", user_text="aprinde lumina", tools_active=True,
    )
    assert out["enabled"] is False
    assert out["effort"] is None
    assert out["auto_reason"] == "control"


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

    glm_out = pc.assistant_turn({"type": "glm"}, msg)
    assert glm_out["reasoning_content"] == "step 1"

    plain = pc.assistant_turn({"type": "openai"}, msg)
    assert "reasoning_content" not in plain


def test_assistant_turn_keeps_empty_reasoning_with_tool_calls():
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
    }
    out = pc.assistant_turn({"type": "deepseek"}, msg)
    assert out["reasoning_content"] == ""
    glm_out = pc.assistant_turn({"type": "glm"}, msg)
    assert glm_out["reasoning_content"] == ""


def test_needs_reasoning_in_tool_loop():
    assert pc.needs_reasoning_in_tool_loop({"type": "deepseek"}) is True
    assert pc.needs_reasoning_in_tool_loop({"type": "grok"}) is True
    assert pc.needs_reasoning_in_tool_loop({"type": "glm"}) is True
    assert pc.needs_reasoning_in_tool_loop({"type": "openai"}) is False


def test_prepare_messages_for_tools_adds_reasoning_field():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "cameras?"},
    ]
    out = ds.prepare_messages_for_tools(msgs)
    assert "reasoning_content" not in out[0]
    assert out[1]["reasoning_content"] == ""
    assert out[1]["content"] == "hello"


def test_prepare_messages_for_request_only_deepseek_tools_thinking():
    msgs = [{"role": "assistant", "content": "x"}]
    thinking = {"enabled": True, "effort": "high"}
    shaped = pc.prepare_messages_for_request(
        {"type": "deepseek"}, msgs, tools=[{"type": "function"}], thinking=thinking,
    )
    assert shaped[0]["reasoning_content"] == ""

    untouched = pc.prepare_messages_for_request(
        {"type": "openai"}, msgs, tools=[{"type": "function"}], thinking=thinking,
    )
    assert "reasoning_content" not in untouched[0]


def test_reasoning_passback_applies_when_thinking_auto_off():
    """Short follow-ups resolve thinking=off, but tools still require pass-back."""
    msgs = [
        {"role": "user", "content": "ce e prin fata casei?"},
        {"role": "assistant", "content": "nimic suspect"},
        {"role": "user", "content": "da ultimul snap"},
    ]
    thinking = {"mode": "auto", "enabled": False, "effort": None}
    shaped = pc.prepare_messages_for_request(
        {"type": "deepseek"}, msgs, tools=[{"type": "function"}], thinking=thinking,
    )
    assert shaped[1]["reasoning_content"] == ""

    no_thinking = pc.prepare_messages_for_request(
        {"type": "deepseek"}, msgs, tools=[{"type": "function"}], thinking=None,
    )
    assert no_thinking[1]["reasoning_content"] == ""


def test_prepare_messages_for_request_skips_when_no_tools():
    msgs = [{"role": "assistant", "content": "x"}]
    shaped = pc.prepare_messages_for_request({"type": "deepseek"}, msgs, tools=None)
    assert "reasoning_content" not in shaped[0]


def test_prepare_messages_for_tools_keeps_existing_reasoning():
    msgs = [{"role": "assistant", "content": "x", "reasoning_content": "step 1"}]
    out = ds.prepare_messages_for_tools(msgs)
    assert out[0]["reasoning_content"] == "step 1"


def test_strip_reasoning_removes_field():
    msgs = [
        {"role": "assistant", "content": "x", "reasoning_content": "cot"},
        {"role": "user", "content": "hi"},
    ]
    out = ds.strip_reasoning(msgs)
    assert "reasoning_content" not in out[0]
    assert out[1] == {"role": "user", "content": "hi"}


def test_is_reasoning_passback_error():
    body = (
        '{"error":{"message":"The `reasoning_content` in the thinking mode '
        'must be passed back to the API.","type":"invalid_request_error"}}'
    )
    assert ds.is_reasoning_passback_error(400, body) is True
    assert ds.is_reasoning_passback_error(500, body) is False
    assert ds.is_reasoning_passback_error(400, '{"error":"bad key"}') is False
