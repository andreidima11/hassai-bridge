"""Gemini and Qwen provider presets + OpenAI-compat URL building."""

from __future__ import annotations

from services.provider_capabilities import preset_capabilities
from services.providers import (
    PROVIDER_PRESETS,
    _build_url,
    normalize_provider_base_url,
    provider_supports_vision,
)


def test_gemini_and_qwen_presets_exist():
    assert "gemini" in PROVIDER_PRESETS
    assert "qwen" in PROVIDER_PRESETS
    assert PROVIDER_PRESETS["gemini"]["requires_key"] is True
    assert PROVIDER_PRESETS["qwen"]["requires_key"] is True
    assert "v1beta/openai" in PROVIDER_PRESETS["gemini"]["base_url"]
    assert "compatible-mode/v1" in PROVIDER_PRESETS["qwen"]["base_url"]


def test_gemini_chat_url_does_not_double_v1():
    provider = {
        "type": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    }
    assert (
        _build_url(provider, "/v1/chat/completions")
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert (
        _build_url(provider, "/v1/models")
        == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    )


def test_gemini_url_strips_pasted_chat_completions():
    raw = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert normalize_provider_base_url(raw) == (
        "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    provider = {"type": "gemini", "base_url": raw}
    assert (
        _build_url(provider, "/v1/chat/completions")
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def test_qwen_intl_and_china_chat_urls():
    intl = {
        "type": "qwen",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    }
    china = {
        "type": "qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    assert (
        _build_url(intl, "/v1/chat/completions")
        == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert (
        _build_url(china, "/v1/chat/completions")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_existing_openai_url_building_unchanged():
    assert (
        _build_url({"base_url": "https://api.openai.com"}, "/v1/chat/completions")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        _build_url({"base_url": "https://api.x.ai/v1"}, "/v1/chat/completions")
        == "https://api.x.ai/v1/chat/completions"
    )
    assert (
        _build_url({"base_url": "https://api.z.ai/api/paas/v4"}, "/v1/chat/completions")
        == "https://api.z.ai/api/paas/v4/chat/completions"
    )


def test_gemini_provider_supports_vision_by_type():
    assert provider_supports_vision({"type": "gemini", "model": "gemini-2.5-flash"})
    assert not provider_supports_vision({"type": "gemini", "model": ""})


def test_preset_capabilities_gemini_qwen_kv():
    assert "kv_cache" in preset_capabilities("gemini")
    assert "kv_cache" in preset_capabilities("qwen")
    assert "thinking" not in preset_capabilities("gemini")
