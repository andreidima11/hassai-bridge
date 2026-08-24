"""Gemini and Qwen provider presets + OpenAI-compat URL building."""

from __future__ import annotations

from services import gemini as gm
from services.provider_capabilities import assistant_turn, prepare_messages_for_request, preset_capabilities, resolve_thinking
from services.providers import (
    PROVIDER_PRESETS,
    _build_url,
    normalize_provider_base_url,
    provider_supports_vision,
)

GEMINI = {"type": "gemini", "model": "gemini-2.5-flash"}


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
    assert "thinking" in preset_capabilities("gemini")
    assert "thinking" in preset_capabilities("glm")


def test_gemini_resolve_thinking_maps_to_reasoning_effort():
    provider = {"type": "gemini", "model": "gemini-2.5-flash", "thinking_mode": "high"}
    out = pc.resolve_thinking(provider, override="high", user_text="plan")
    assert out["enabled"] is True
    assert out["effort"] == "high"


def test_gemini_apply_thinking_payload():
    provider = {"type": "gemini", "model": "gemini-2.5-flash"}
    payload = {"model": "gemini-2.5-flash"}
    gm.apply_thinking_payload(payload, {"enabled": True, "effort": "high"}, provider=provider)
    assert payload["reasoning_effort"] == "high"


def test_gemini_off_uses_none_on_25_flash():
    provider = {"type": "gemini", "model": "gemini-2.5-flash", "thinking_mode": "off"}
    out = pc.resolve_thinking(provider, override="off", user_text="salut")
    assert out["enabled"] is False
    assert out["effort"] == "none"
    payload = {"model": "gemini-2.5-flash"}
    gm.apply_thinking_payload(payload, out, provider=provider)
    assert payload["reasoning_effort"] == "none"


def test_gemini_skips_reasoning_none_when_tools_loaded():
    provider = {"type": "gemini", "model": "gemini-2.5-flash", "thinking_mode": "off"}
    thinking = pc.resolve_thinking(
        provider, override="off", user_text="aprinde lumina", tools_active=True,
    )
    payload = {"model": "gemini-2.5-flash", "tools": [{"type": "function"}]}
    gm.apply_thinking_payload(payload, thinking, provider=provider)
    assert "reasoning_effort" not in payload


def test_gemini_retryable_400_detects_invalid_argument_with_tools():
    payload = {"tools": [{"type": "function"}]}
    body = '[{"error":{"message":"Request contains an invalid argument.","status":"INVALID_ARGUMENT"}}]'
    assert gm.is_gemini_retryable_400(400, body, payload)
    assert not gm.is_gemini_retryable_400(400, body, {})


def test_gemini_injects_skip_on_all_replayed_tool_calls():
    msgs = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
        ],
    }]
    out = prepare_messages_for_request(GEMINI, msgs, tools=[{"type": "function"}])
    for call in out[0]["tool_calls"]:
        assert call["extra_content"]["google"]["thought_signature"] == gm.SKIP_SIGNATURE


def test_gemini_assistant_turn_preserves_thought_signature():
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "extra_content": {"google": {"thought_signature": "sig-abc"}},
            "function": {"name": "ha_call_service", "arguments": "{}"},
        }],
    }
    out = assistant_turn(GEMINI, msg)
    assert out["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-abc"


def test_gemini_prepare_messages_injects_skip_for_replayed_tools():
    msgs = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "ha_call_service", "arguments": "{}"},
        }],
    }]
    out = prepare_messages_for_request(GEMINI, msgs, tools=[{"type": "function"}])
    sig = out[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
    assert sig == gm.SKIP_SIGNATURE


def test_gemini_stream_merge_keeps_extra_content():
    entry = {"id": "", "name": "", "arguments": ""}
    gm.merge_tool_call_delta(entry, {
        "id": "call_9",
        "function": {"name": "ha_list_entities", "arguments": '{"domain": "light"}'},
        "extra_content": {"google": {"thought_signature": "sig-stream"}},
    })
    built = gm.build_tool_call(entry, fallback_idx=0)
    assert built["id"] == "call_9"
    assert built["extra_content"]["google"]["thought_signature"] == "sig-stream"


def test_gemini_thought_signature_error_detection():
    body = '{"error":{"message":"Function call is missing a thought_signature in functionCall parts."}}'
    assert gm.is_thought_signature_error(400, body)
    assert not gm.is_thought_signature_error(400, '{"error":{"message":"bad request"}}')
