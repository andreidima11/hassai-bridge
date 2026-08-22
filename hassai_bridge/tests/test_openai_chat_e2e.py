"""End-to-end: chat_completion must never POST max_tokens to OpenAI."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services import providers as prov


def test_chat_completion_openai_gpt56_never_sends_max_tokens():
    provider = {
        "id": "openai_chatgpt",
        "type": "openai",
        "name": "ChatGPT",
        "model": "gpt-5.6-chat-latest",
        "max_tokens": 2048,
        "temperature": 0.7,
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "timeout": 30,
    }
    tools = [{"type": "function", "function": {"name": "search_web", "parameters": {"type": "object"}}}]

    captured = {}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }
    mock_resp.text = "{}"

    async def capture_post(url, *, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = dict(json or {})
        return mock_resp

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=capture_post)
    mock_client.is_closed = False

    async def _run():
        with patch.object(prov, "_get_client", return_value=mock_client):
            return await prov.chat_completion(
                [{"role": "user", "content": "hi"}],
                provider=provider,
                tools=tools,
                stream=False,
                cache_conv_id="sess-1",
            )

    result = asyncio.run(_run())
    assert result["choices"]
    body = captured["json"]
    assert "max_tokens" not in body, f"must not send max_tokens, got keys={sorted(body)}"
    assert body["max_completion_tokens"] == 2048
    assert body["model"] == "gpt-5.6-chat-latest"
    assert body["reasoning_effort"] == "none"  # gpt-5.6 + tools
    assert "temperature" not in body  # gpt-5 rejects custom temperature
    assert "openai.com" in captured["url"]


def test_chat_completion_stream_openai_never_sends_max_tokens():
    provider = {
        "id": "openai_chatgpt",
        "type": "openai",
        "name": "ChatGPT",
        "model": "gpt-5.6",
        "max_tokens": 900,
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "timeout": 30,
    }

    captured = {}

    class _FakeStream:
        def __init__(self):
            self.status_code = 200
            self.request = MagicMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}'
            yield "data: [DONE]"

        async def aread(self):
            return b""

    def capture_stream(method, url, *, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = dict(json or {})
        return _FakeStream()

    mock_client = MagicMock()
    mock_client.stream = MagicMock(side_effect=capture_stream)
    mock_client.is_closed = False

    async def _run():
        chunks = []
        with patch.object(prov, "_get_client", return_value=mock_client):
            async for line in prov.chat_completion_stream(
                [{"role": "user", "content": "hi"}],
                provider=provider,
                tools=[{"type": "function", "function": {"name": "x"}}],
            ):
                chunks.append(line)
        return chunks

    chunks = asyncio.run(_run())
    body = captured["json"]
    assert "max_tokens" not in body
    assert body["max_completion_tokens"] == 900
    assert body["reasoning_effort"] == "none"
    assert chunks
