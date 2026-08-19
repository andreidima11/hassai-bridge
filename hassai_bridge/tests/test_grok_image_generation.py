import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

from services import grok
from services import provider_capabilities as pc


def test_supports_image_generation_grok_only():
    assert pc.supports_image_generation({"type": "grok"})
    assert not pc.supports_image_generation({"type": "deepseek"})
    assert not pc.supports_image_generation({"type": "openai"})


def test_build_image_generation_tool():
    tool = pc.build_image_generation_tool({"type": "grok", "image_model": "grok-imagine-image-2.0"})
    assert tool["function"]["name"] == "generate_image"
    assert "prompt" in tool["function"]["parameters"]["properties"]


def test_generate_image_persists_b64(monkeypatch, tmp_path):
    monkeypatch.setattr("services.chat_media.UPLOADS_ROOT", tmp_path / "uploads")
    provider = {
        "type": "grok",
        "base_url": "https://api.x.ai/v1",
        "api_key": "test-key",
    }
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    b64 = base64.b64encode(png_bytes).decode("ascii")
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.text = ""
    api_response.json.return_value = {"data": [{"b64_json": b64}]}
    api_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=api_response)

    with patch("services.providers._get_client", return_value=mock_client), patch(
        "services.providers._build_url", return_value="https://api.x.ai/v1/images/generations"
    ), patch("services.providers._build_headers", return_value={"Authorization": "Bearer test"}):
        result = asyncio.run(
            grok.generate_image(
                provider,
                "A red circle on white background",
                user_id="alice",
                session_id="sess-1",
            )
        )

    assert result["attachments"]
    assert len(result["attachments"]) == 1
    assert "/api/chat/media/" in result["text"]
    mock_client.post.assert_awaited_once()
    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["model"] == "grok-imagine-image-2.0"
    assert payload["prompt"] == "A red circle on white background"


def test_generate_image_downloads_url(monkeypatch, tmp_path):
    monkeypatch.setattr("services.chat_media.UPLOADS_ROOT", tmp_path / "uploads")
    provider = {"type": "grok", "base_url": "https://api.x.ai/v1", "api_key": "test-key"}
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"y" * 40

    api_response = MagicMock()
    api_response.status_code = 200
    api_response.text = ""
    api_response.json.return_value = {"data": [{"url": "https://cdn.example.com/img.png"}]}
    api_response.raise_for_status = MagicMock()

    img_response = MagicMock()
    img_response.raise_for_status = MagicMock()
    img_response.content = png_bytes
    img_response.headers = {"content-type": "image/png"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=api_response)
    mock_client.get = AsyncMock(return_value=img_response)

    with patch("services.providers._get_client", return_value=mock_client), patch(
        "services.providers._build_url", return_value="https://api.x.ai/v1/images/generations"
    ), patch("services.providers._build_headers", return_value={"Authorization": "Bearer test"}):
        result = asyncio.run(
            grok.generate_image(provider, "sunset over mountains", user_id="bob")
        )

    assert result["attachments"]
    mock_client.get.assert_awaited_once_with("https://cdn.example.com/img.png", timeout=60)
