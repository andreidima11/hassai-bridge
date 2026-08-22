"""Tests for OpenAI Chat Completions request mapping and prompt cache."""

from __future__ import annotations

import json

from services import openai_api as oai
from services import provider_capabilities as pc
from services.providers import _apply_token_limit, _finalize_chat_payload, _skip_temperature


def test_detects_openai_by_type_and_base_url():
    assert oai.is_openai_provider({"type": "openai"})
    assert oai.is_openai_provider({"type": "custom", "base_url": "https://api.openai.com/v1"})
    assert oai.is_openai_provider({"type": "custom", "name": "ChatGPT", "base_url": "https://gateway.example/v1"})
    assert oai.is_openai_provider({"type": "custom", "name": "ChatGPT"})
    assert not oai.is_openai_provider({"type": "deepseek", "base_url": "https://api.deepseek.com"})
    assert not oai.is_openai_provider({"type": "local"})
    assert not oai.is_openai_provider(
        {"type": "local", "name": "ChatGPT", "base_url": "http://localhost:1234"}
    )


def test_chatgpt_without_base_url_remaps_gpt4o():
    provider = {"type": "custom", "name": "ChatGPT", "model": "gpt-4o", "max_tokens": 1024}
    payload = {"model": "gpt-4o"}
    _apply_token_limit(payload, provider)
    oai.sanitize_outbound_chat_payload(payload, provider)
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 1024


def test_sanitize_drops_duplicate_max_tokens():
    payload = {"model": "gpt-4o", "max_tokens": 500, "max_completion_tokens": 800}
    oai.sanitize_outbound_chat_payload(payload, {"type": "openai", "model": "gpt-4o"})
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 800


def test_remaps_max_tokens_to_max_completion_tokens():
    payload = {"model": "gpt-5", "max_tokens": 2048, "temperature": 0.7}
    oai.apply_request_payload(payload, {"type": "openai", "model": "gpt-5"})
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 2048
    assert "temperature" not in payload


def test_gpt4o_keeps_temperature_but_remaps_tokens():
    payload = {"model": "gpt-4o", "max_tokens": 1024, "temperature": 0.4}
    oai.apply_request_payload(payload, {"type": "openai", "model": "gpt-4o"})
    assert payload["max_completion_tokens"] == 1024
    assert payload["temperature"] == 0.4


def test_chatgpt_named_provider_remaps_even_if_type_wrong():
    provider = {
        "type": "custom",
        "name": "ChatGPT",
        "model": "gpt-5.2",
        "max_tokens": 2048,
        "base_url": "https://api.openai.com/v1",
    }
    payload = {"model": "gpt-5.2"}
    _apply_token_limit(payload, provider)
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 2048
    _finalize_chat_payload(payload, provider, cache_conv_id="s1")
    assert "max_tokens" not in payload
    assert payload["prompt_cache_key"] == "s1"


def test_misTyped_gpt5_model_still_remaps():
    provider = {"type": "glm", "name": "ChatGPT", "model": "gpt-5", "max_tokens": 900, "base_url": "https://proxy.example/v1"}
    payload = {"model": "gpt-5"}
    _apply_token_limit(payload, provider)
    assert payload.get("max_completion_tokens") == 900
    assert "max_tokens" not in payload


def test_local_gpt_named_model_keeps_max_tokens():
    provider = {"type": "local", "model": "gpt-oss-20b", "max_tokens": 512, "base_url": "http://127.0.0.1:1234"}
    payload = {"model": "gpt-oss-20b"}
    _apply_token_limit(payload, provider)
    assert payload["max_tokens"] == 512
    assert "max_completion_tokens" not in payload


def test_local_type_openai_url_remaps_gpt56():
    """Mis-typed local provider pointing at OpenAI must not send max_tokens."""
    provider = {
        "type": "local",
        "name": "ChatGPT",
        "model": "gpt-5.6-chat-latest",
        "max_tokens": 2048,
        "base_url": "https://api.openai.com/v1",
    }
    payload = {"model": "gpt-5.6-chat-latest"}
    _apply_token_limit(payload, provider)
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 2048


def test_openrouter_style_model_id_remaps():
    provider = {
        "type": "custom",
        "name": "OpenRouter",
        "model": "openai/gpt-5.6",
        "max_tokens": 1500,
        "base_url": "https://openrouter.ai/api/v1",
    }
    payload = {"model": "openai/gpt-5.6"}
    _apply_token_limit(payload, provider)
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 1500


def test_sanitize_by_request_url_strips_max_tokens():
    provider = {"type": "custom", "name": "Weird", "model": "my-model", "max_tokens": 800}
    payload = {"model": "my-model", "max_tokens": 800}
    url = "https://api.openai.com/v1/chat/completions"
    oai.sanitize_outbound_chat_payload(payload, provider, request_url=url)
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 800


def test_gpt56_model_detection():
    assert oai.looks_like_openai_model("gpt-5.6")
    assert oai.looks_like_openai_model("gpt-5.6-chat-latest")
    assert oai.looks_like_openai_model("gpt-5.6-sol-high")
    assert oai.looks_like_openai_model("openai/gpt-5.6")
    assert oai.uses_max_completion_tokens({"type": "openai"}, "gpt-5.6")


def test_non_openai_left_alone():
    payload = {"model": "deepseek-chat", "max_tokens": 500, "temperature": 0.2}
    oai.apply_request_payload(payload, {"type": "deepseek"})
    assert payload["max_tokens"] == 500
    assert payload["temperature"] == 0.2


def test_providers_finalize_path():
    provider = {"type": "openai", "model": "o3-mini", "max_tokens": 900, "temperature": 0.9}
    payload = {"model": "o3-mini"}
    _apply_token_limit(payload, provider)
    assert payload.get("max_completion_tokens") == 900
    assert "max_tokens" not in payload
    if not _skip_temperature(provider, None, model="o3-mini"):
        payload["temperature"] = provider["temperature"]
    _finalize_chat_payload(payload, provider, cache_conv_id="sess-abc")
    assert payload == {
        "model": "o3-mini",
        "max_completion_tokens": 900,
        "prompt_cache_key": "sess-abc",
    }


def test_prompt_cache_key_and_stream_usage_flag():
    payload = {"model": "gpt-4o", "stream": True, "max_tokens": 100}
    oai.apply_request_payload(
        payload,
        {"type": "openai", "model": "gpt-4o"},
        cache_conv_id="  chat-42  ",
    )
    assert payload["prompt_cache_key"] == "chat-42"
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_completion_tokens"] == 100


def test_prompt_cache_key_truncated():
    assert oai.prompt_cache_key("") is None
    assert oai.prompt_cache_key(None) is None
    long = "x" * 200
    assert len(oai.prompt_cache_key(long)) == 128


def test_cache_tokens_from_usage():
    hit, miss = oai.cache_tokens_from_usage(
        {
            "prompt_tokens": 1000,
            "prompt_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 50},
        }
    )
    assert hit == 800
    assert miss == 200

    assert oai.cache_tokens_from_usage({}) == (0, 0)
    assert pc.cache_tokens_from_usage(
        {"type": "openai"},
        {"prompt_tokens": 500, "prompt_tokens_details": {"cached_tokens": 120}},
    ) == (120, 380)
    assert pc.cache_tokens_from_usage(
        {"type": "custom", "base_url": "https://api.openai.com/v1"},
        {"prompt_tokens": 200, "prompt_tokens_details": {"cached_tokens": 50}},
    ) == (50, 150)


def test_openai_kv_cache_capability():
    caps = pc.preset_capabilities("openai")
    assert "kv_cache" in caps
    assert caps["kv_cache"]["context_budget"] == 120000
    assert pc.supports_kv_cache({"type": "openai"}) is True
    assert pc.supports_kv_cache({"type": "custom", "base_url": "https://api.openai.com/v1"}) is True
    assert pc.kv_context_budget({"type": "openai"}) == 120000


def test_openai_type_chatgpt_name_gpt56():
    """User scenario: type openai, display name ChatGPT, gpt-5.6 model."""
    provider = {
        "type": "openai",
        "name": "ChatGPT",
        "model": "gpt-5.6-chat-latest",
        "max_tokens": 2048,
        "base_url": "https://api.openai.com/v1",
    }
    payload = {"model": "gpt-5.6-chat-latest", "stream": True, "max_tokens": 999}
    url = "https://api.openai.com/v1/chat/completions"
    oai.finalize_http_payload(payload, provider, request_url=url)
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 999


def test_finalize_http_payload_openai_type():
    provider = {"type": "openai", "name": "ChatGPT", "model": "gpt-5.6"}
    payload = {"model": "gpt-5.6", "max_tokens": 512}
    oai.finalize_http_payload(
        payload,
        provider,
        request_url="https://api.openai.com/v1/chat/completions",
    )
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 512


def test_httpx_client_has_no_sync_request_hooks():
    """AsyncClient awaits hooks — a sync hook returns None and crashes every request."""
    import services.providers as prov

    prov._client = None
    client = prov._get_client()
    assert list(client.event_hooks.get("request") or []) == []


def test_restricted_model_detection():
    assert oai.is_restricted_sampling_model("o1")
    assert oai.is_restricted_sampling_model("o3-mini")
    assert oai.is_restricted_sampling_model("gpt-5")
    assert not oai.is_restricted_sampling_model("chatgpt-4o-latest")
    assert not oai.is_restricted_sampling_model("gpt-4o")
    assert not oai.is_restricted_sampling_model("gpt-4.1")


def test_gpt56_plus_detection():
    assert oai.is_gpt56_plus_model("gpt-5.6")
    assert oai.is_gpt56_plus_model("gpt-5.6-chat-latest")
    assert oai.is_gpt56_plus_model("gpt-5.6-sol")
    assert oai.is_gpt56_plus_model("openai/gpt-5.6-terra")
    assert oai.is_gpt56_plus_model("gpt-5.7")
    assert not oai.is_gpt56_plus_model("gpt-5")
    assert not oai.is_gpt56_plus_model("gpt-5.4")
    assert not oai.is_gpt56_plus_model("gpt-4o")


def test_gpt56_with_tools_sets_reasoning_effort_none():
    payload = {
        "model": "gpt-5.6-chat-latest",
        "tools": [{"type": "function", "function": {"name": "search_web"}}],
        "max_tokens": 1000,
    }
    provider = {"type": "openai", "name": "ChatGPT", "model": "gpt-5.6-chat-latest", "max_tokens": 1000}
    oai.sanitize_outbound_chat_payload(
        payload,
        provider,
        request_url="https://api.openai.com/v1/chat/completions",
    )
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 1000
    assert payload["reasoning_effort"] == "none"


def test_wire_hook_rewrites_max_tokens_in_httpx_request():
    import httpx

    req = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        content=b'{"model":"gpt-5.6","max_tokens":512,"messages":[]}',
        headers={"Content-Type": "application/json"},
    )
    oai.rewrite_openai_request_body(req)
    body = json.loads(req.content)
    assert "max_tokens" not in body
    assert body["max_completion_tokens"] == 512


def test_wire_hook_sets_reasoning_effort_for_gpt56_tools():
    import httpx

    req = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        content=b'{"model":"gpt-5.6-sol","tools":[{"type":"function"}],"messages":[]}',
        headers={"Content-Type": "application/json"},
    )
    oai.rewrite_openai_request_body(req)
    body = json.loads(req.content)
    assert body["reasoning_effort"] == "none"
