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
