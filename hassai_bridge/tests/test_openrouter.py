"""OpenRouter provider helpers."""

from services import openrouter as ovr
from services.providers import PROVIDER_PRESETS, _finalize_chat_payload, _provider_request_headers
from services.provider_capabilities import preset_capabilities


def test_openrouter_preset():
    assert "openrouter" in PROVIDER_PRESETS
    assert PROVIDER_PRESETS["openrouter"]["requires_key"] is True
    assert "openrouter.ai" in PROVIDER_PRESETS["openrouter"]["base_url"]
    assert "kv_cache" in preset_capabilities("openrouter")


def test_is_openrouter_by_type_and_url():
    assert ovr.is_openrouter_provider({"type": "openrouter"})
    assert ovr.is_openrouter_provider({
        "type": "custom",
        "base_url": "https://openrouter.ai/api/v1",
    })
    assert not ovr.is_openrouter_provider({"type": "openai", "base_url": "https://api.openai.com/v1"})


def test_attribution_headers():
    headers = ovr.attribution_headers()
    assert headers["HTTP-Referer"].startswith("https://")
    assert headers["X-OpenRouter-Title"] == "HASSAI Bridge"
    assert headers["X-Title"] == "HASSAI Bridge"
    assert "personal-agent" in headers["X-OpenRouter-Categories"]


def test_provider_request_headers_include_attribution():
    headers = _provider_request_headers({
        "type": "openrouter",
        "api_key": "sk-or-test",
        "base_url": "https://openrouter.ai/api/v1",
    })
    assert headers["Authorization"] == "Bearer sk-or-test"
    assert "HTTP-Referer" in headers
    assert headers["X-OpenRouter-Title"] == "HASSAI Bridge"
    assert "X-OpenRouter-Categories" in headers


def test_resolve_reply_model_prefers_response():
    assert ovr.resolve_reply_model(
        response={"model": "anthropic/claude-sonnet-4"},
        configured="openrouter/auto",
    ) == "anthropic/claude-sonnet-4"
    assert ovr.resolve_reply_model(
        stream_model="google/gemini-2.5-flash",
        configured="openrouter/auto",
    ) == "google/gemini-2.5-flash"
    assert ovr.resolve_reply_model(configured="meta-llama/llama-3.3-70b-instruct") == (
        "meta-llama/llama-3.3-70b-instruct"
    )
    assert ovr.resolve_reply_model(configured="default") == ""
    assert ovr.resolve_reply_model() == ""


def test_normalize_openrouter_options():
    opts = ovr.normalize_openrouter_options({
        "fallback_models": "a/b, a/b, c/d:free",
        "sort": "LATENCY",
        "allow_fallbacks": False,
        "data_collection": "deny",
        "zdr": 1,
        "context_compression": True,
    })
    assert opts["fallback_models"] == ["a/b", "c/d:free"]
    assert opts["sort"] == "latency"
    assert opts["allow_fallbacks"] is False
    assert opts["data_collection"] == "deny"
    assert opts["zdr"] is True
    assert opts["context_compression"] is True


def test_apply_request_extras_models_and_provider():
    payload = {"model": "openai/gpt-4o-mini", "messages": []}
    provider = {
        "type": "openrouter",
        "openrouter": {
            "fallback_models": ["openai/gpt-4o-mini", "google/gemma-2-9b-it:free"],
            "sort": "throughput",
            "allow_fallbacks": False,
            "data_collection": "deny",
            "zdr": True,
            "context_compression": True,
        },
    }
    ovr.apply_request_extras(payload, provider)
    # Primary is not duplicated in the fallbacks list.
    assert payload["models"] == ["google/gemma-2-9b-it:free"]
    assert payload["provider"] == {
        "sort": "throughput",
        "allow_fallbacks": False,
        "data_collection": "deny",
        "zdr": True,
    }
    assert payload["plugins"] == [{"id": "context-compression"}]


def test_finalize_chat_payload_wires_openrouter_extras():
    payload = {"model": "anthropic/claude-sonnet-4", "messages": []}
    provider = {
        "type": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "openrouter": {
            "fallback_models": ["meta-llama/llama-3.3-70b-instruct"],
            "sort": "price",
            "context_compression": False,
        },
    }
    _finalize_chat_payload(payload, provider, request_url="https://openrouter.ai/api/v1/chat/completions")
    assert payload["models"] == ["meta-llama/llama-3.3-70b-instruct"]
    assert payload["provider"]["sort"] == "price"
    assert payload["plugins"] == [{"id": "context-compression", "enabled": False}]


def test_apply_request_extras_noop_for_other_providers():
    payload = {"model": "gpt-4o", "messages": []}
    ovr.apply_request_extras(payload, {"type": "openai"})
    assert "models" not in payload
    assert "provider" not in payload
    assert "plugins" not in payload
