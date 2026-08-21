from services import grok
from services import provider_capabilities as pc


def test_grok_preset_capabilities():
    caps = pc.preset_capabilities("grok")
    assert "thinking" in caps
    assert "kv_cache" in caps
    assert caps["kv_cache"]["context_budget"] == 480000
    assert caps.get("image_generation")


def test_grok_resolve_thinking_off_maps_to_low():
    provider = {"type": "grok", "model": "grok-4.6", "thinking_mode": "auto"}
    out = grok.resolve_thinking(provider, override="off", user_text="plan architecture")
    assert out["effort"] == "low"


def test_grok_resolve_thinking_max_uses_xhigh_on_46():
    provider = {"type": "grok", "model": "grok-4.6", "thinking_mode": "auto"}
    out = grok.resolve_thinking(provider, override="max", user_text="hi")
    assert out["effort"] == "xhigh"


def test_grok_apply_thinking_low_on_multimodal():
    payload = {"model": "grok-4.6", "messages": []}
    grok.apply_thinking_payload(
        payload,
        {"effort": "xhigh", "enabled": True},
        has_images=True,
    )
    assert payload["reasoning_effort"] == "low"
    assert "temperature" not in payload


def test_grok_skips_reasoning_effort_on_unsupported_models():
    for mid in (
        "grok-4.20-0309-reasoning",
        "grok-4.20-reasoning",
        "grok-build-0.1",
        "grok-4.3",
        "grok-4.20-0309-non-reasoning",
    ):
        payload = {"model": mid, "temperature": 0.7}
        grok.apply_thinking_payload(
            payload,
            {"effort": "high", "enabled": True},
            provider={"type": "grok", "model": mid},
        )
        assert "reasoning_effort" not in payload, mid
        assert "temperature" not in payload, mid


def test_grok_reasoning_effort_allowlist():
    assert grok.supports_reasoning_effort("grok-4.6")
    assert grok.supports_reasoning_effort("grok-4.5")
    assert grok.supports_reasoning_effort("grok-4.20-multi-agent-0309")
    assert not grok.supports_reasoning_effort("grok-4.20-0309-reasoning")
    assert not grok.supports_reasoning_effort("grok-build-0.1")


def test_grok_cache_tokens_from_usage():
    hit, miss = grok.cache_tokens_from_usage({
        "prompt_tokens": 200,
        "prompt_tokens_details": {"cached_tokens": 120},
    })
    assert hit == 120
    assert miss == 80


def test_provider_cache_tokens_grok():
    provider = {"type": "grok"}
    hit, miss = pc.cache_tokens_from_usage(provider, {
        "prompt_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 40},
    })
    assert hit == 40
    assert miss == 10
