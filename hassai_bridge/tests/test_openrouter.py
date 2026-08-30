"""OpenRouter provider helpers."""

from services import openrouter as ovr
from services.providers import PROVIDER_PRESETS, _provider_request_headers
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
    assert headers["X-Title"] == "HASSAI Bridge"


def test_provider_request_headers_include_attribution():
    headers = _provider_request_headers({
        "type": "openrouter",
        "api_key": "sk-or-test",
        "base_url": "https://openrouter.ai/api/v1",
    })
    assert headers["Authorization"] == "Bearer sk-or-test"
    assert "HTTP-Referer" in headers
    assert headers["X-Title"] == "HASSAI Bridge"


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
