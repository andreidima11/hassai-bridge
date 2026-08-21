"""Tests for OpenAI Chat Completions request mapping."""

from __future__ import annotations

from services import openai_api as oai
from services.providers import _apply_token_limit, _finalize_chat_payload, _skip_temperature


def test_detects_openai_by_type_and_base_url():
    assert oai.is_openai_provider({"type": "openai"})
    assert oai.is_openai_provider({"type": "custom", "base_url": "https://api.openai.com/v1"})
    assert not oai.is_openai_provider({"type": "deepseek", "base_url": "https://api.deepseek.com"})
    assert not oai.is_openai_provider({"type": "local"})


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


def test_non_openai_left_alone():
    payload = {"model": "deepseek-chat", "max_tokens": 500, "temperature": 0.2}
    oai.apply_request_payload(payload, {"type": "deepseek"})
    assert payload["max_tokens"] == 500
    assert payload["temperature"] == 0.2


def test_providers_finalize_path():
    provider = {"type": "openai", "model": "o3-mini", "max_tokens": 900, "temperature": 0.9}
    payload = {"model": "o3-mini"}
    _apply_token_limit(payload, provider)
    assert payload["max_tokens"] == 900
    if not _skip_temperature(provider, None, model="o3-mini"):
        payload["temperature"] = provider["temperature"]
    _finalize_chat_payload(payload, provider)
    assert payload == {"model": "o3-mini", "max_completion_tokens": 900}


def test_restricted_model_detection():
    assert oai.is_restricted_sampling_model("o1")
    assert oai.is_restricted_sampling_model("o3-mini")
    assert oai.is_restricted_sampling_model("gpt-5")
    assert not oai.is_restricted_sampling_model("chatgpt-4o-latest")
    assert not oai.is_restricted_sampling_model("gpt-4o")
    assert not oai.is_restricted_sampling_model("gpt-4.1")
