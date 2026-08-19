import base64
import tempfile
from pathlib import Path

import pytest

from services import chat_content as cc
from services import chat_media as cm


def test_content_text_from_multimodal():
    content = [
        {"type": "text", "text": "  hello  "},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    assert cc.content_text(content) == "hello"
    assert cc.has_images(content) is True


def test_build_multimodal_content_from_attachments(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "UPLOADS_ROOT", tmp_path)
    user_id = "tester"
    tiny = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    data_url = f"data:image/png;base64,{tiny}"
    saved = cm.persist_attachments_from_content(
        user_id,
        [{"type": "image_url", "image_url": {"url": data_url}}],
    )
    assert len(saved) == 1
    built = cc.build_multimodal_content("what is this?", saved, user_id=user_id)
    assert isinstance(built, list)
    assert built[0]["type"] == "text"
    assert built[1]["type"] == "image_url"


def test_sanitize_does_not_crash_on_multimodal():
    from routers.chat import _sanitize_message_roles

    messages = [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]},
    ]
    cleaned = _sanitize_message_roles(messages)
    assert cleaned[0]["role"] == "user"
    assert isinstance(cleaned[0]["content"], list)


def test_messages_have_images():
    assert cc.messages_have_images([]) is False
    assert cc.messages_have_images([{"role": "user", "content": "hello"}]) is False
    assert cc.messages_have_images([
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]},
    ]) is True


def test_provider_supports_vision():
    from services import providers as prov

    assert prov.provider_supports_vision({"model": "gpt-4o-mini"}) is True
    assert prov.provider_supports_vision({"model": "claude-3-5-sonnet"}) is True
    assert prov.provider_supports_vision({"model": "llama-3.1-8b"}) is False
    assert prov.provider_supports_vision({"model": "gpt-4o-mini", "supports_vision": False}) is False
    assert prov.provider_supports_vision({"model": "llama-3.1-8b", "supports_vision": True}) is True


def test_recall_provider_uses_image_provider_when_set():
    from routers.chat import _recall_provider

    active = {"id": "primary", "model": "llama-3.1-8b"}
    secondary = {"id": "secondary", "model": "gpt-4o-mini"}
    vision = {"id": "vision", "model": "gpt-4o"}
    tool_calls = [{"function": {"name": "web_search"}}]

    assert _recall_provider(tool_calls, active, secondary)["id"] == "secondary"
    assert _recall_provider(tool_calls, active, secondary, image_provider=vision)["id"] == "vision"
    assert _recall_provider(
        tool_calls, active, secondary, image_provider=vision, vision_direct=False,
    )["id"] == "secondary"
    assert _recall_provider(
        [{"function": {"name": "ha_call_service"}}], active, secondary, image_provider=vision,
    )["id"] == "vision"


def test_normalize_vision_mode_provider():
    from services import providers as prov

    assert prov.normalize_vision_mode("relay") == "relay"
    assert prov.normalize_vision_mode(None, default="direct") == "direct"


def test_resolve_image_provider(monkeypatch):
    from services import providers as prov

    primary = {"id": "p1", "vision_provider": "vis1", "secondary_provider": "sec1"}
    vision = {"id": "vis1", "model": "gpt-4o"}
    secondary = {"id": "sec1", "model": "gpt-4o-mini"}

    monkeypatch.setattr(prov, "get_vision_provider", lambda p=None: vision)
    assert prov.resolve_image_provider(primary, secondary) is vision

    monkeypatch.setattr(prov, "get_vision_provider", lambda p=None: None)
    assert prov.resolve_image_provider(primary, secondary) is secondary

    monkeypatch.setattr(prov, "get_secondary_provider", lambda p=None: secondary)
    assert prov.resolve_image_provider(primary) is secondary


def test_vision_required_error_localized():
    from routers.chat import _vision_required_error

    en = _vision_required_error({"language": "en"})
    assert en.status_code == 400
    assert "Vision LLM" in en.body.decode()

    ro = _vision_required_error({"language": "ro"})
    assert ro.status_code == 400
    assert "llm vision" in ro.body.decode().lower()
