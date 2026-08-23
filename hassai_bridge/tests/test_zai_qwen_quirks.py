"""GLM (Z.ai) and Qwen (DashScope) request quirks that otherwise return HTTP 400."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services import chat_content as cc
from services import provider_capabilities as pc
from services import providers as prov
from services import qwen as qw
from services import zai as zi


GLM = {
    "id": "glm1", "name": "GLM", "type": "glm", "model": "glm-5.2",
    "base_url": "https://api.z.ai/api/paas/v4", "api_key": "k",
    "temperature": 1.8, "max_tokens": 2048, "timeout": 30,
}
QWEN = {
    "id": "qw1", "name": "Qwen", "type": "qwen", "model": "qwen3-235b-a22b",
    "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "api_key": "k",
    "temperature": 0.7, "max_tokens": 2048, "timeout": 30,
}


def _capture_chat(provider, **kwargs):
    captured = {}
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    resp.text = "{}"

    async def post(url, *, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = dict(json or {})
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=post)
    client.is_closed = False

    async def run():
        with patch.object(prov, "_get_client", return_value=client):
            return await prov.chat_completion(
                kwargs.pop("messages", [{"role": "user", "content": "salut"}]),
                provider=provider,
                **kwargs,
            )

    asyncio.run(run())
    return captured["json"], captured["url"]


# ── GLM ────────────────────────────────────────────

def test_glm_temperature_is_clamped_to_one():
    body, _ = _capture_chat(GLM)
    assert body["temperature"] == 1.0


def test_glm_keeps_max_tokens_not_max_completion_tokens():
    body, _ = _capture_chat(GLM)
    assert body["max_tokens"] == 2048
    assert "max_completion_tokens" not in body


def test_glm_tool_choice_is_forced_to_auto():
    tools = [{"type": "function", "function": {"name": "f", "description": "d",
                                               "parameters": {"type": "object", "properties": {}}}}]
    body, _ = _capture_chat(GLM, tools=tools, tool_choice="required")
    assert body["tool_choice"] == "auto"


def test_glm_tools_get_required_description_and_parameters():
    body, _ = _capture_chat(GLM, tools=[{"type": "function", "function": {"name": "ping"}}])
    fn = body["tools"][0]["function"]
    assert fn["description"]
    assert fn["parameters"] == {"type": "object", "properties": {}}


def test_glm_thinking_payload_shape():
    thinking = zi.resolve_thinking({**GLM, "thinking_mode": "high"}, user_text="planuim ceva")
    payload = {"model": "glm-5.2"}
    zi.apply_thinking_payload(payload, thinking, provider=GLM)
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_glm_thinking_off_disables_and_asks_for_no_effort():
    thinking = zi.resolve_thinking({**GLM, "thinking_mode": "off"})
    payload = {"model": "glm-5.2"}
    zi.apply_thinking_payload(payload, thinking, provider=GLM)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["reasoning_effort"] == "none"


def test_glm_53_reports_thinking_as_forced_on():
    provider = {**GLM, "model": "glm-5.3", "thinking_mode": "off"}
    thinking = zi.resolve_thinking(provider)
    assert thinking["enabled"] is True
    assert thinking["auto_reason"] == "forced_by_model"
    # 5.3 only accepts low/high/max — never "none".
    assert thinking["effort"] == "low"


def test_glm_cache_tokens_derive_the_miss_count():
    hit, miss = zi.cache_tokens_from_usage(
        {"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 400}}
    )
    assert (hit, miss) == (400, 600)
    assert pc.cache_tokens_from_usage(GLM, {"prompt_tokens": 10}) == (0, 10)


# ── Qwen ───────────────────────────────────────────

def test_qwen_never_asks_for_thinking_on_a_non_streaming_call():
    # DashScope rejects this outright on the open-source builds:
    # "parameter.enable_thinking only support stream call".
    body, _ = _capture_chat(QWEN, thinking={"enabled": True, "budget": 16384})
    assert body["enable_thinking"] is False
    assert "thinking_budget" not in body


def test_qwen_enables_thinking_while_streaming():
    payload = {"model": QWEN["model"], "stream": True}
    qw.apply_thinking_payload(payload, {"enabled": True, "budget": 16384}, provider=QWEN)
    assert payload["enable_thinking"] is True
    assert payload["thinking_budget"] == 16384


def test_qwen_thinking_models_get_no_flag_at_all():
    provider = {**QWEN, "model": "qwen3-235b-a22b-thinking-2507"}
    payload = {"model": provider["model"], "stream": True}
    qw.apply_thinking_payload(payload, {"enabled": True}, provider=provider)
    assert "enable_thinking" not in payload
    assert qw.resolve_thinking({**provider, "thinking_mode": "off"})["enabled"] is True


def test_qwen_tool_choice_keeps_auto_and_none_only():
    assert qw.sanitize_tool_choice("none") == "none"
    assert qw.sanitize_tool_choice("auto") == "auto"
    assert qw.sanitize_tool_choice({"type": "function", "function": {"name": "f"}}) == "auto"
    assert qw.sanitize_tool_choice(None) is None


def test_qwen_uses_max_tokens():
    body, _ = _capture_chat(QWEN)
    assert body["max_tokens"] == 2048
    assert "max_completion_tokens" not in body


def test_qwen_cache_tokens_from_openai_shaped_usage():
    assert qw.cache_tokens_from_usage(
        {"prompt_tokens": 3019, "prompt_tokens_details": {"cached_tokens": 2048}}
    ) == (2048, 971)


# ── Shared: images must not reach a text-only model ──

def test_history_images_are_stripped_for_providers_without_vision():
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "ce e aici?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]},
        {"role": "assistant", "content": "o pisica"},
        {"role": "user", "content": "si acum?"},
    ]
    text_only = {"type": "qwen", "model": "qwen-plus"}
    shaped = pc.prepare_messages_for_request(text_only, messages)
    assert not cc.messages_have_images(shaped)
    assert "ce e aici?" in shaped[0]["content"]


def test_vision_capable_provider_keeps_its_images():
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "ce e aici?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]}]
    vision = {"type": "qwen", "model": "qwen3-vl-plus", "supports_vision": True}
    shaped = pc.prepare_messages_for_request(vision, messages)
    assert cc.messages_have_images(shaped)


def test_presets_expose_thinking_for_glm_and_qwen():
    assert "thinking" in pc.preset_capabilities("glm")
    assert "thinking" in pc.preset_capabilities("qwen")
    assert "kv_cache" in pc.preset_capabilities("glm")
